from __future__ import annotations

import importlib.util
from pathlib import Path


def test_repeat_gate_requires_gain_in_both_paired_val_runs():
    script = Path(__file__).resolve().parents[1] / "scripts/alfworld_hypothesis_confirm.py"
    spec = importlib.util.spec_from_file_location("alfworld_hypothesis_confirm", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    decide = module.confirmation_decision
    assert decide(16, 16, 17, 17, has_errors=False) == "CONFIRMED_ACCEPT"
    assert decide(16, 17, 17, 17, has_errors=False) == "INCONCLUSIVE_VARIATION"
    assert decide(16, 17, 17, 16, has_errors=False) == "REJECT_REPEAT"
    assert decide(16, 16, 17, 18, has_errors=True) == "INCONCLUSIVE_MODEL_ERRORS"
