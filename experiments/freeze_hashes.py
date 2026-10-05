"""Print SHA-256 hashes of the artefacts that must be frozen before the first TEST-split run.

Usage: .venv/bin/python experiments/freeze_hashes.py
Copy the output into DECISIONS.md §Freeze hashes. After that, any change to these files requires a new dated entry
in DECISIONS.md and invalidates the freeze.
"""

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FROZEN = [
    "DEFENSE_SPEC.md",
    "agents/defenses.py",            # B1–B4 implementation incl. gate tables and lexicon
    "agents/adaptive_attacks.py",    # A2 templates
    "agents/native_llm.py",          # model interface (prompt rendering / parsing)
    "EXPERIMENT_MATRIX.md",
    "metrics.md",
    "evaluation/metrics.py",
    "configs/benchmark.yaml",
    "configs/models.yaml",
    "experiments/run_cell.py",
]

if __name__ == "__main__":
    for rel in FROZEN:
        print(f"| {rel} | {hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()} |")
