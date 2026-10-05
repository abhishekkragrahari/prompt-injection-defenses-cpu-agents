#!/bin/bash
# S1 DEV-split smoke checks (pipeline verification only; DEV split; not results).
set -u
cd "$(dirname "$0")/.."
R=S1-dev-smoke-$(date +%Y%m%dT%H%M%S)
run() { PYTHONPATH=. .venv/bin/python experiments/run_cell.py --run-id "$R" --split dev "$@" 2>&1 | grep -v "Warning\|n_ctx_seq\|warn(" ; }
A0T="banking:user_task_0 banking:user_task_2"
A1T="banking:user_task_2"
run --model qwen3-4b --defense B0 --attack A0 --tasks $A0T
for D in B1 B2 B4; do run --model qwen3-4b --defense $D --attack A0 --tasks $A0T --no-warmup; done
for D in B0 B1 B2 B4; do run --model qwen3-4b --defense $D --attack A1 --tasks $A1T --no-warmup; done
for D in B2 B4; do run --model qwen3-4b --defense $D --attack A2 --tasks $A1T --no-warmup; done
for A in A0 A1; do run --model qwen3-4b --defense B3 --attack $A --tasks $A1T --no-warmup \
    --detector-model protectai/deberta-v3-base-prompt-injection-v2 --detector-safe-label SAFE; done
run --model granite4-micro --defense B4 --attack A1 --tasks $A1T --no-warmup
echo "RUN_ID=$R"
