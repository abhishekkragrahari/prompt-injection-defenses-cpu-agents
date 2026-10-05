#!/bin/bash
# Main matrix (S2) + B4 ablations (S3), full design per DECISIONS.md D22. TEST split. Serial. Offline. Resumable.
# Usage: caffeinate -i experiments/run_main.sh     (stop anytime with Ctrl-C; re-run the same command to resume)
# Resume rule: completed cells (cell_summary.json present) are skipped. An interrupted cell is renamed to
# <cell>__INCOMPLETE_<timestamp> (preserved, never deleted, excluded from analysis) and re-run from scratch.
set -u
cd "$(dirname "$0")/.."
export HF_HUB_OFFLINE=1
RUN_ID=MAIN-20260927          # fixed so that every session writes to the same run
B3="--detector-safe-label LABEL_0"
LOG=logs/run_main_progress.log
mkdir -p logs

cells=()
# Priority 1: A1 (primary security contrasts), both models, all defenses
for M in qwen3-4b granite4-micro; do for D in B0 B1 B2 B3 B4; do cells+=("$M $D A1 full"); done; done
# Priority 2: A0 benign cells for defenses (B0/A0 is taken from P0, D22)
for M in qwen3-4b granite4-micro; do for D in B1 B2 B3 B4; do cells+=("$M $D A0 full"); done; done
# Priority 3: A2 adaptive templates
for M in qwen3-4b granite4-micro; do for D in B2 B3 B4; do cells+=("$M $D A2 full"); done; done
# Priority 4: B4 internal-validity ablations (M1 only; A0 + A1)
for V in noS1 noS3 noS4; do for A in A0 A1; do cells+=("qwen3-4b B4 $A $V"); done; done

total=${#cells[@]}; i=0
for c in "${cells[@]}"; do
  i=$((i+1)); read -r M D A V <<< "$c"
  suffix=$([ "$V" = full ] && echo "" || echo "-$V")
  dir="results/raw/$RUN_ID/${M}__${D}${suffix}__${A}__test"
  if [ -f "$dir/cell_summary.json" ]; then echo "[$i/$total] skip (done) $dir"; continue; fi
  if [ -d "$dir" ]; then
    mv "$dir" "${dir}__INCOMPLETE_$(date +%Y%m%dT%H%M%S)"
    echo "$(date) moved interrupted cell aside: $dir" >> "$LOG"
  fi
  echo "$(date) START [$i/$total] $M $D $A $V" | tee -a "$LOG"
  extra=$([ "$D" = B3 ] && echo "$B3" || echo "")
  PYTHONPATH=. .venv/bin/python experiments/run_cell.py --run-id "$RUN_ID" --split test \
      --model "$M" --defense "$D" --attack "$A" --gate-variant "$V" $extra 2>&1 | grep -v "Warning\|n_ctx_seq\|warn(\|Device set"
  if [ -f "$dir/cell_summary.json" ]; then echo "$(date) DONE  [$i/$total] $dir" | tee -a "$LOG"
  else echo "$(date) FAILED [$i/$total] $dir — stopping" | tee -a "$LOG"; exit 1; fi
done
echo "$(date) ALL CELLS COMPLETE" | tee -a "$LOG"
