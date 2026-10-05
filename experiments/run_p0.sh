#!/bin/bash
# P0 pilot (EXPERIMENT_MATRIX.md §7; determinism subset per DECISIONS.md D21). TEST split. Serial. Offline.
# Usage: caffeinate -i experiments/run_p0.sh
set -eu
cd "$(dirname "$0")/.."
export HF_HUB_OFFLINE=1
R=P0-$(date +%Y%m%dT%H%M%S)
A0_DET="banking:user_task_5 banking:user_task_6 banking:user_task_7 banking:user_task_8 banking:user_task_9"
A1_DET="banking:user_task_5 banking:user_task_6"   # 2 tasks x 3 injections = 6 pairs; first 5 pairs are compared
run() { PYTHONPATH=. .venv/bin/python experiments/run_cell.py --split test --defense B0 "$@" 2>&1 | grep -v "Warning\|n_ctx_seq\|warn(" ; }
for M in qwen3-4b granite4-micro; do
  run --run-id "$R" --model $M --attack A0                                   # competence cell (= main B0/A0 cell)
  run --run-id "$R-det1" --model $M --attack A1 --tasks $A1_DET --no-warmup  # determinism: A1 run 1
  run --run-id "$R-det2" --model $M --attack A0 --tasks $A0_DET              # determinism: A0 re-run
  run --run-id "$R-det2" --model $M --attack A1 --tasks $A1_DET --no-warmup  # determinism: A1 run 2
done
echo "RUN_ID=$R"
echo "Next: PYTHONPATH=. .venv/bin/python experiments/p0_report.py $R"
