# Evaluating Prompt-Injection Defenses for CPU-Only Small Language Model Agents

Code, configuration and raw data for an empirical study of three inexpensive prompt-injection defenses
(spotlighting, PromptGuard-2-22M, and a deterministic runtime-policy gate) for 3–4B tool-calling agents
(Qwen3-4B-Instruct-2507, Granite-4.0-Micro) running entirely on a CPU, evaluated on the AgentDojo
Banking and Slack suites.

## Contents

| Path | Content |
|---|---|
| [plan.md](plan.md) | Research question, pre-registered hypotheses, scope |
| [DECISIONS.md](DECISIONS.md) | Dated decision log, including the freeze hashes (the post-hoc B3 diagnostic is entry D23) |
| [EXPERIMENT_MATRIX.md](EXPERIMENT_MATRIX.md) | Factors, cells, adaptive templates, statistics plan |
| [metrics.md](metrics.md) | Metric definitions (BTSR, ATSR, raw ASR, ASR_C, VR, FPR_task, cost) |
| [DEFENSE_SPEC.md](DEFENSE_SPEC.md) | Defense conditions B0–B4, gate rules, ablations |
| [BENCHMARK_PROTOCOL.md](BENCHMARK_PROTOCOL.md) | AgentDojo version, splits, injection sample, attacks |
| `agents/` | In-process llama.cpp connector for AgentDojo, defenses, adaptive (A2) templates |
| `evaluation/` | Metric and statistics code |
| `experiments/` | Episode runner, run scripts, report and figure generation, B3 payload diagnostic |
| `configs/` | Pinned models (repository, revision, SHA-256) and benchmark settings |
| `results/raw/` | Raw per-episode logs of the pilot and main runs (write-once) |
| `results/processed/` | Generated report (`main_report.md` / `.json`) with all numbers used in the paper |
| `logs/` | Environment record, screening protocol, run logs |
| `tests/` | Unit tests |

## Reference machine

MacBook Pro (2020), Intel Core i7-1068NG7 (4 cores / 8 threads, AVX-512), 32 GB RAM, macOS 26.7 (x86_64), no GPU.

## Setup

```bash
python3 -m pip install --user uv
uv python install 3.11
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python --only-binary cryptography,torch -r requirements.lock.txt
```

Model weights are not redistributed. Download the GGUF files listed in `configs/models.yaml` into `models/`;
their SHA-256 checksums are verified at every process start.
PromptGuard-2-22M (B3) is gated: accept the Llama license on Hugging Face and run `huggingface-cli login`.

## Reproducing the results

```bash
.venv/bin/python -m pytest -q tests
bash experiments/run_main.sh                        # all main-study cells (CPU only; long-running)
PYTHONPATH=. .venv/bin/python experiments/main_report.py MAIN-20260927 P0-20260927T110335  # tables, hypothesis checks, derived quantities
PYTHONPATH=. .venv/bin/python experiments/make_figures.py MAIN-20260927  # figures
```

`main_report.py` regenerates every reported number from the raw logs in `results/raw/`, so the published
results can be checked without re-running the experiments.
