#!/bin/bash
# B3 (PromptGuard-2-22M) DEV-split smoke checks — pipeline verification only; DEV split; not results.
set -u
cd "$(dirname "$0")/.."
export HF_HUB_OFFLINE=1
R=S1-b3-dev-smoke-$(date +%Y%m%dT%H%M%S)
run() { PYTHONPATH=. .venv/bin/python experiments/run_cell.py --run-id "$R" --split dev --defense B3 \
          --detector-safe-label LABEL_0 "$@" 2>&1 | grep -v "Warning\|n_ctx_seq\|warn(\|Device set" ; }
run --model qwen3-4b --attack A0 --tasks banking:user_task_0 banking:user_task_2
run --model qwen3-4b --attack A1 --tasks banking:user_task_2 --no-warmup
run --model qwen3-4b --attack A2 --tasks banking:user_task_2 --no-warmup
run --model granite4-micro --attack A1 --tasks banking:user_task_2 --no-warmup
echo "RUN_ID=$R"
