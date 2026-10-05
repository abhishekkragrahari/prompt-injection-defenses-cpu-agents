"""Stage 2: run benign AgentDojo tasks end-to-end with the native in-process agent.

Pipeline and cost check only (no attacks, no defenses). Outputs are kept as raw
logs but are not research results.

Usage:
  .venv/bin/python experiments/stage2_single_task.py --model qwen3-4b --suite banking --tasks user_task_0
Outputs: results/raw/stage2/<timestamp>_<model>/
"""

import argparse
import datetime
import json
import random
import time
from pathlib import Path

import numpy as np
import psutil
import yaml
from agentdojo.agent_pipeline import AgentPipeline, InitQuery, SystemMessage, ToolsExecutionLoop, ToolsExecutor
from agentdojo.agent_pipeline.agent_pipeline import load_system_message
from agentdojo.task_suite.load_suites import get_suite
from llama_cpp import Llama

from agents.native_llm import NativeLlamaCppLLM

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_VERSION = "v1.2.2"



def _jsonable(messages):
    def conv(o):
        if hasattr(o, "model_dump"):
            return o.model_dump()
        return str(o)
    return json.loads(json.dumps(list(messages), default=conv))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--suite", default="banking")
    ap.add_argument("--tasks", nargs="+", default=["user_task_0"])
    ap.add_argument("--n-ctx", type=int, default=None)
    ap.add_argument("--system-message", default=None, help="DIAGNOSTIC ONLY: override AgentDojo system message")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "configs/models.yaml").read_text())
    rt, spec = cfg["runtime"], cfg["models"][args.model]
    n_ctx = args.n_ctx or rt["n_ctx"]
    random.seed(rt["seed"])
    np.random.seed(rt["seed"])

    out_dir = ROOT / "results/raw/stage2" / f"{datetime.datetime.now():%Y%m%dT%H%M%S}_{args.model}"
    out_dir.mkdir(parents=True)

    llama = Llama(model_path=str(ROOT / spec["file"]), n_ctx=n_ctx, n_threads=rt["n_threads"], seed=rt["seed"],
                  verbose=False)
    llm = NativeLlamaCppLLM(llama, spec["dialect"], seed=rt["seed"], temperature=rt["temperature"])
    pipeline = AgentPipeline([SystemMessage(args.system_message or load_system_message(None)), InitQuery(), llm,
                              ToolsExecutionLoop([ToolsExecutor(), llm])])
    pipeline.name = f"native-{args.model}"

    suite = get_suite(BENCHMARK_VERSION, args.suite)
    config = {"model": args.model, "gguf_sha256": spec["sha256"], "benchmark_version": BENCHMARK_VERSION,
              "suite": args.suite, "tasks": args.tasks, "n_ctx": n_ctx, "system_message_override": args.system_message, **{k: rt[k] for k in ("n_threads", "temperature", "seed")}}
    (out_dir / "config.json").write_text(json.dumps(config, indent=2))

    summary = []
    for task_id in args.tasks:
        task = suite.get_user_task_by_id(task_id)
        llm.call_log = []
        captured = {}
        orig_query = pipeline.query

        def capturing_query(*a, **kw):
            res = orig_query(*a, **kw)
            captured["messages"] = res[3]
            return res

        pipeline.query = capturing_query
        t0 = time.perf_counter()
        utility, _ = suite.run_task_with_pipeline(pipeline, task, injection_task=None, injections={})
        wall = time.perf_counter() - t0
        pipeline.query = orig_query

        record = {"task": task_id, "prompt": task.PROMPT, "utility": bool(utility), "wall_s": round(wall, 1),
                  "n_model_calls": len(llm.call_log),
                  "max_prompt_tokens": max((c["prompt_tokens"] for c in llm.call_log), default=0),
                  "sum_prompt_tokens": sum(c["prompt_tokens"] for c in llm.call_log),
                  "sum_completion_tokens": sum(c["completion_tokens"] for c in llm.call_log),
                  "parse_errors": sum(c["parse_error"] is not None for c in llm.call_log),
                  "rss_gb": round(psutil.Process().memory_info().rss / 2**30, 2)}
        (out_dir / f"{task_id}.json").write_text(json.dumps(
            {**record, "calls": llm.call_log, "messages": _jsonable(captured.get("messages", []))}, indent=2))
        summary.append(record)
        print(json.dumps(record))

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"Raw logs: {out_dir}")


if __name__ == "__main__":
    main()
