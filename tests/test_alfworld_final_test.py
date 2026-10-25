from __future__ import annotations

import importlib.util
import hashlib
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


def test_isolated_round2_skill_excludes_round1_sibling(tmp_path):
    source = tmp_path / "submission" / "skills"
    skill = source / "alfworld-strategy" / "SKILL.md"
    helper = skill.parent / "scripts" / "safe_send.py"
    helper.parent.mkdir(parents=True)
    skill.write_text("---\nname: alfworld-strategy\ndescription: test\n---\n", encoding="utf-8")
    helper.write_text("print('test')\n", encoding="utf-8")
    other = source / "spreadsheet-workflow" / "SKILL.md"
    other.parent.mkdir()
    other.write_text("Round 1 content", encoding="utf-8")
    frozen = {"skill_sha256": hashlib.sha256(skill.read_bytes()).hexdigest(),
              "helper_sha256": hashlib.sha256(helper.read_bytes()).hexdigest()}
    isolated = _module._isolate_skill(skill, tmp_path / "run", frozen)
    assert [p.name for p in isolated.iterdir()] == ["alfworld-strategy"]
    assert (isolated / "alfworld-strategy" / "scripts" / "safe_send.py").read_bytes() == helper.read_bytes()
