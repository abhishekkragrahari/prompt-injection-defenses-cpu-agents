"""Run one experimental cell (model × defense × attack × split) in its own process.

Implements EXPERIMENT_MATRIX.md §4–5: model hash check, seeded greedy decoding, one discarded warm-up episode,
KV-cache reset per episode, per-episode RSS sampling, write-once raw logs.

Usage:
  PYTHONPATH=. .venv/bin/python experiments/run_cell.py --run-id R --model qwen3-4b --defense B4 --attack A1 --split dev
"""

import argparse
import datetime
import hashlib
import json
import platform
import random
import resource
import sys
import threading
import time
from pathlib import Path

import numpy as np
import psutil
import yaml
from agentdojo.attacks.attack_registry import load_attack
from agentdojo.task_suite.load_suites import get_suite
from llama_cpp import Llama

import agents.adaptive_attacks  # noqa: F401  (registers A2 attacks)
from agents.defenses import DEFENSES, GATE_VARIANTS, WindowedPIDetector, build_pipeline
from agents.native_llm import NativeLlamaCppLLM

ROOT = Path(__file__).resolve().parents[1]
PROMPTGUARD = "meta-llama/Llama-Prompt-Guard-2-22M"
PROMPTGUARD_REVISION = "11614a155199674a0a95e6602d6ab0417b790ed0"  # DECISIONS.md D20


class RssSampler:
    """Samples this process's RSS every `interval` seconds; `peak` is the maximum seen."""

    def __init__(self, interval: float = 0.5):
        self.interval, self.peak, self._stop = interval, 0, threading.Event()
        self._proc = psutil.Process()

    def __enter__(self):
        self.peak = self._proc.memory_info().rss
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()
        return self

    def _run(self):
        while not self._stop.wait(self.interval):
            self.peak = max(self.peak, self._proc.memory_info().rss)

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join()
        self.peak = max(self.peak, self._proc.memory_info().rss)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def jsonable(obj):
    def conv(o):
        return o.model_dump() if hasattr(o, "model_dump") else str(o)
    return json.loads(json.dumps(obj, default=conv))


def calls_as_dicts(calls) -> list[dict]:
    return [{"function": c.function, "args": jsonable(dict(c.args))} for c in (calls or [])]


def episode_list(bench: dict, split: str, attack: str, task_filter: list[str] | None):
    eps = []
    for suite_name, tasks in bench["splits"][split].items():
        for ut in tasks:
            if task_filter and f"{suite_name}:{ut}" not in task_filter:
                continue
            if attack == "A0":
                eps.append((suite_name, ut, None))
            else:
                eps.extend((suite_name, ut, it) for it in bench["injection_sample"][suite_name])
    return eps


def run_episode(suite, built, llm, attack_obj, user_task_id, injection_task_id):
    user_task = suite.get_user_task_by_id(user_task_id)
    injection_task = suite.get_injection_task_by_id(injection_task_id) if injection_task_id else None
    injections = attack_obj.attack(user_task, injection_task) if attack_obj and injection_task else {}

    # Ground truth for auxiliary metrics (metrics.md §4), computed on a fresh copy of the pre-task environment.
    env0 = user_task.init_environment(suite.load_and_inject_default_environment({}))
    user_gt = calls_as_dicts(user_task.ground_truth(env0.model_copy(deep=True)))
    inj_gt = calls_as_dicts(injection_task.ground_truth(env0.model_copy(deep=True))) if injection_task else []

    llm.reset_episode()
    if built.tool_filter:
        built.tool_filter.last_kept, built.tool_filter.last_removed = [], []
    if built.detector:
        built.detector.events = []
    if built.gate:
        built.gate.audit = []
    captured = {}
    orig = built.pipeline.query

    def capturing(*a, **kw):
        res = orig(*a, **kw)
        captured["messages"] = res[3]
        return res

    built.pipeline.query = capturing
    with RssSampler() as rss:
        t0 = time.perf_counter()
        utility, security = suite.run_task_with_pipeline(built.pipeline, user_task, injection_task, injections)
        wall = time.perf_counter() - t0
    built.pipeline.query = orig

    messages = captured.get("messages", [])
    tool_results = [{"function": m["tool_call"].function, "args": jsonable(dict(m["tool_call"].args)),
                     "error": m.get("error")} for m in messages if m["role"] == "tool"]
    proposed = [c for m in messages if m["role"] == "assistant" for c in calls_as_dicts(m.get("tool_calls"))]
    return {
        "suite": suite.name, "user_task": user_task_id, "injection_task": injection_task_id,
        "utility": bool(utility), "security": bool(security) if injection_task else None,
        "wall_s": round(wall, 3), "rss_peak_sampled_bytes": rss.peak,
        "calls": list(llm.call_log), "proposed_tool_calls": proposed, "tool_results": tool_results,
        "defense_events": {
            "tool_filter": {"kept": built.tool_filter.last_kept, "removed": built.tool_filter.last_removed}
            if built.tool_filter else None,
            "detector": list(built.detector.events) if built.detector else None,
            "gate": list(built.gate.audit) if built.gate else None,
        },
        "user_ground_truth": user_gt, "injection_ground_truth": inj_gt,
        "injections": injections, "messages": jsonable(list(messages)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--defense", required=True, choices=DEFENSES)
    ap.add_argument("--attack", required=True, choices=["A0", "A1", "A2"])
    ap.add_argument("--split", required=True, choices=["dev", "test"])
    ap.add_argument("--gate-variant", default="full", choices=GATE_VARIANTS)
    ap.add_argument("--detector-model", default=PROMPTGUARD)
    ap.add_argument("--detector-safe-label", default=None, help="label name meaning 'benign' for the detector")
    ap.add_argument("--detector-revision", default=None,
                    help="classifier revision; defaults to the pinned PromptGuard revision when using PromptGuard")
    ap.add_argument("--tasks", nargs="*", default=None, help="optional filter, e.g. banking:user_task_0")
    ap.add_argument("--no-warmup", action="store_true")
    args = ap.parse_args()
    if args.attack == "A2" and args.defense not in ("B2", "B3", "B4"):
        sys.exit("A2 is defined only for B2, B3, B4 (EXPERIMENT_MATRIX.md §2)")

    models = yaml.safe_load((ROOT / "configs/models.yaml").read_text())
    bench = yaml.safe_load((ROOT / "configs/benchmark.yaml").read_text())
    rt, spec = models["runtime"], models["models"][args.model]

    variant = "" if args.gate_variant == "full" else f"-{args.gate_variant}"
    cell = f"{args.model}__{args.defense}{variant}__{args.attack}__{args.split}"
    out_dir = ROOT / "results/raw" / args.run_id / cell
    if out_dir.exists():
        sys.exit(f"Refusing to overwrite existing raw results: {out_dir}")

    actual = sha256(ROOT / spec["file"])
    if actual != spec["sha256"]:
        sys.exit(f"Model checksum mismatch for {args.model}: {actual}")

    random.seed(rt["seed"])
    np.random.seed(rt["seed"])
    t0 = time.perf_counter()
    llama = Llama(model_path=str(ROOT / spec["file"]), n_ctx=rt["n_ctx"], n_threads=rt["n_threads"], seed=rt["seed"],
                  verbose=False)
    load_s = time.perf_counter() - t0
    llm = NativeLlamaCppLLM(llama, spec["dialect"], seed=rt["seed"], temperature=rt["temperature"],
                            max_tokens=rt.get("max_tokens", 1024))

    detector, detector_standin = None, False
    if args.defense == "B3":
        detector_standin = args.detector_model != PROMPTGUARD
        if args.detector_safe_label is None:
            sys.exit("--detector-safe-label is required for B3 (verify the label names on the model card)")
        revision = args.detector_revision or (PROMPTGUARD_REVISION if args.detector_model == PROMPTGUARD else None)
        detector = WindowedPIDetector(args.detector_model, safe_label=args.detector_safe_label, revision=revision)
    built = build_pipeline(llm, args.model, args.defense, args.gate_variant, detector)

    out_dir.mkdir(parents=True)
    config = {
        "run_id": args.run_id, "cell": cell, "model": args.model, "gguf_sha256": actual, "defense": args.defense,
        "gate_variant": args.gate_variant, "attack": args.attack, "split": args.split,
        "attack_name": bench["attacks"]["A1"] if args.attack == "A1" else
        (bench["attacks"]["A2"][args.defense] if args.attack == "A2" else None),
        "detector_model": args.detector_model if args.defense == "B3" else None,
        "detector_is_standin": detector_standin, "pipeline_name": built.pipeline.name,
        "detector_config": {"revision": detector.revision, "safe_label": detector.safe_label,
                            "threshold": detector.threshold, "max_tokens": detector.max_tokens, "mode": "message",
                            "aggregation": "flag if any window flagged"} if detector else None,
        "benchmark": {k: bench[k] for k in ("benchmark_version", "agentdojo_package", "agentdojo_commit")},
        "runtime": rt, "task_filter": args.tasks, "model_load_s": round(load_s, 2),
        "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "host": {"platform": platform.platform(), "python": sys.version.split()[0],
                 "cpu_count_physical": psutil.cpu_count(logical=False)},
    }
    (out_dir / "cell_config.json").write_text(json.dumps(config, indent=2))

    suites = {name: get_suite(bench["benchmark_version"], name) for name in bench["splits"][args.split]}
    suites.setdefault("banking", get_suite(bench["benchmark_version"], "banking"))
    attack_objs = {}
    if args.attack != "A0":
        for name, suite in suites.items():
            attack_objs[name] = load_attack(config["attack_name"], suite, built.pipeline)

    if not args.no_warmup:
        w = bench["warmup_episode"]
        rec = run_episode(suites[w["suite"]], built, llm, None, w["user_task"], None)
        (out_dir / "warmup.json").write_text(json.dumps({**rec, "note": "warm-up; excluded from metrics"}, indent=2))

    episodes = episode_list(bench, args.split, args.attack, args.tasks)
    for i, (suite_name, ut, it) in enumerate(episodes):
        rec = run_episode(suites[suite_name], built, llm, attack_objs.get(suite_name), ut, it)
        eid = f"{suite_name}__{ut}__{it or 'none'}"
        rec = {"episode_id": eid, "cell": cell, "model": args.model, "defense": args.defense,
               "gate_variant": args.gate_variant, "attack": args.attack, **rec}
        (out_dir / f"{eid}.json").write_text(json.dumps(rec, indent=2))
        print(f"[{i + 1}/{len(episodes)}] {eid} util={rec['utility']} sec={rec['security']} "
              f"calls={len(rec['calls'])} wall={rec['wall_s']}s", flush=True)

    summary = {"episodes": len(episodes), "ru_maxrss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               "finished_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    (out_dir / "cell_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"Cell complete: {out_dir}")


if __name__ == "__main__":
    main()
