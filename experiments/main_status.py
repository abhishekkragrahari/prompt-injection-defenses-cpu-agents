"""Progress and ETA of the main run (read-only). Usage: .venv/bin/python experiments/main_status.py"""
import json
import time
from pathlib import Path

RUN = Path(__file__).resolve().parents[1] / "results/raw/MAIN-20260927"
EXPECTED = {"A0": 32, "A1": 96, "A2": 96}
MEAN_S = {("qwen3-4b", "A0"): 68.4, ("qwen3-4b", "A1"): 107.9, ("qwen3-4b", "A2"): 107.9,
          ("granite4-micro", "A0"): 48.0, ("granite4-micro", "A1"): 89.3, ("granite4-micro", "A2"): 89.3}  # P0
cells = []
for m in ("qwen3-4b", "granite4-micro"):
    cells += [(m, d, "A1", "") for d in ("B0", "B1", "B2", "B3", "B4")]
for m in ("qwen3-4b", "granite4-micro"):
    cells += [(m, d, "A0", "") for d in ("B1", "B2", "B3", "B4")]
for m in ("qwen3-4b", "granite4-micro"):
    cells += [(m, d, "A2", "") for d in ("B2", "B3", "B4")]
cells += [("qwen3-4b", "B4", a, f"-{v}") for v in ("noS1", "noS3", "noS4") for a in ("A0", "A1")]
done_eps = total_eps = 0
remaining_s = 0.0
for m, d, a, v in cells:
    n = EXPECTED[a]
    total_eps += n
    cell = RUN / f"{m}__{d}{v}__{a}__test"
    k = len([p for p in cell.glob("*__*.json")]) if cell.exists() else 0
    k = n if (cell / "cell_summary.json").exists() else min(k, n)
    done_eps += k
    remaining_s += (n - k) * MEAN_S[(m, a)] * (1.25 if d == "B1" else 1.0)
print(f"episodes {done_eps}/{total_eps}; estimated remaining {remaining_s / 3600:.1f} h "
      f"(P0-based, ±20%); now {time.strftime('%Y-%m-%d %H:%M')}")
