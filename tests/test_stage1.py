"""Stage 1 checks: pinned models are present and match their recorded checksums."""
import hashlib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / "configs/models.yaml").read_text())


@pytest.mark.parametrize("name", list(CFG["models"]))
def test_model_file_matches_checksum(name):
    spec = CFG["models"][name]
    path = ROOT / spec["file"]
    assert path.exists(), f"missing {path}; see README Stage 1"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    assert h.hexdigest() == spec["sha256"]


def test_core_imports():
    import agentdojo  # noqa: F401
    import llama_cpp  # noqa: F401
    import torch
    import transformers
    assert torch.__version__.startswith("2.2")
    assert transformers.__version__.startswith("4.")
