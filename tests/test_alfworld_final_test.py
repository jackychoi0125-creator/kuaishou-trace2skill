from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_script = Path(__file__).resolve().parents[1] / "scripts/alfworld_final_test.py"
_spec = importlib.util.spec_from_file_location("alfworld_final_test", _script)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)


def test_official_test_score_requires_all_ids_and_marks_model_errors():
    expected = {"test:0000", "test:0001"}
    rows = [{"id": "test:0000", "hard": 1},
            {"id": "test:0001", "hard": 0, "terminal_model_error": True}]
    assert _module._score(rows, expected) == (1, ["test:0001"])
    with pytest.raises(RuntimeError, match="task IDs"):
        _module._score(rows[:1], expected)
