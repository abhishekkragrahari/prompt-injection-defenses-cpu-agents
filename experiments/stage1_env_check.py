"""Stage 1: environment verification.

Records the software/hardware environment, verifies pinned model checksums,
measures CPU inference throughput and memory for each SLM, and runs a small
tool-call format smoke test. This is a feasibility check, not an experiment:
its outputs are not research results.

Usage: .venv/bin/python experiments/stage1_env_check.py
Outputs: logs/stage1/<timestamp>/
"""

import datetime
import hashlib
import importlib.metadata as md
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

import psutil
import yaml

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ["agentdojo", "llama_cpp_python", "torch", "transformers", "numpy",
            "pandas", "scipy", "openai", "pydantic", "huggingface_hub", "psutil", "pytest"]

# Tool-call prompt format used by AgentDojo's LocalLLM (agentdojo 0.1.35).
SMOKE_SYSTEM = """You are a helpful assistant with access to these functions:
{"name": "calculator", "description": "Evaluate an arithmetic expression", "parameters": {"expression": "string"}}
{"name": "send_email", "description": "Send an email", "parameters": {"to": "string", "subject": "string", "body": "string"}}

To call a function, output exactly: <function=function_name>{"param": "value"}</function>
If no function is needed, answer directly."""

SMOKE_CASES = [
    ("needs_calculator", "What is 1234 * 5678? Use a tool.", "calculator"),
    ("needs_email", "Email alice@example.test with subject 'Hi' and body 'See you at 3'.", "send_email"),
    ("no_tool", "What is the capital of France?", None),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def environment() -> dict:
    versions = {}
    for p in PACKAGES:
        try:
            versions[p] = md.version(p)
        except md.PackageNotFoundError:
            versions[p] = None
    cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
    return {
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "os": platform.platform(),
        "machine": platform.machine(),
        "cpu": cpu,
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "ram_gb": round(psutil.virtual_memory().total / 2**30, 1),
        "python": sys.version,
        "packages": versions,
    }


def benchmark_model(name: str, spec: dict, runtime: dict, out_dir: Path) -> dict:
    from llama_cpp import Llama

    proc = psutil.Process()
    rss_before = proc.memory_info().rss
    t0 = time.perf_counter()
    llm = Llama(model_path=str(ROOT / spec["file"]), n_ctx=runtime["n_ctx"], n_threads=runtime["n_threads"],
                seed=runtime["seed"], verbose=False)
    load_s = time.perf_counter() - t0
    rss_loaded = proc.memory_info().rss

    # Throughput: ~500-token prompt, 128 generated tokens, greedy.
    prompt_text = "The quick brown fox jumps over the lazy dog. " * 50
    msgs = [{"role": "user", "content": prompt_text + "\nSummarise the text above in three sentences."}]
    t0 = time.perf_counter()
    r = llm.create_chat_completion(messages=msgs, max_tokens=128, temperature=runtime["temperature"], seed=runtime["seed"])
    wall = time.perf_counter() - t0
    usage = r["usage"]

    smoke = []
    for case_id, user, expected in SMOKE_CASES:
        t0 = time.perf_counter()
        out = llm.create_chat_completion(
            messages=[{"role": "system", "content": SMOKE_SYSTEM}, {"role": "user", "content": user}],
            max_tokens=160, temperature=runtime["temperature"], seed=runtime["seed"])
        text = out["choices"][0]["message"]["content"] or ""
        called = None
        if "<function=" in text:
            called = text.split("<function=", 1)[1].split(">", 1)[0].strip()
        smoke.append({"case": case_id, "expected_tool": expected, "called_tool": called,
                      "match": called == expected, "latency_s": round(time.perf_counter() - t0, 2), "raw_output": text})

    result = {
        "model": name,
        "file": spec["file"],
        "load_s": round(load_s, 2),
        "rss_increase_gb": round((rss_loaded - rss_before) / 2**30, 2),
        "rss_peak_gb": round(proc.memory_info().rss / 2**30, 2),
        "throughput": {"prompt_tokens": usage["prompt_tokens"], "completion_tokens": usage["completion_tokens"],
                       "wall_s": round(wall, 2),
                       "approx_end_to_end_tok_per_s": round(usage["completion_tokens"] / wall, 2)},
        "smoke_test": smoke,
    }
    (out_dir / f"{name}.json").write_text(json.dumps(result, indent=2))
    del llm
    return result


def main():
    cfg = yaml.safe_load((ROOT / "configs/models.yaml").read_text())
    out_dir = ROOT / "logs/stage1" / datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    out_dir.mkdir(parents=True)

    env = environment()
    (out_dir / "environment.json").write_text(json.dumps(env, indent=2))
    print(json.dumps(env, indent=2))

    for name, spec in cfg["models"].items():
        actual = sha256(ROOT / spec["file"])
        ok = actual == spec["sha256"]
        print(f"[{name}] sha256 {'OK' if ok else 'MISMATCH ' + actual}")
        if not ok:
            sys.exit(f"Checksum mismatch for {name}; aborting.")
        res = benchmark_model(name, spec, cfg["runtime"], out_dir)
        print(json.dumps({k: v for k, v in res.items() if k != "smoke_test"}, indent=2))
        for s in res["smoke_test"]:
            print(f"  smoke {s['case']:17s} expected={s['expected_tool']} called={s['called_tool']} "
                  f"match={s['match']} ({s['latency_s']}s)")
    print(f"Logs: {out_dir}")


if __name__ == "__main__":
    main()
