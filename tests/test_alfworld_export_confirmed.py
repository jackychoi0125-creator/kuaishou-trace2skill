from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

_script = Path(__file__).resolve().parents[1] / "scripts/alfworld_export_confirmed.py"
_spec = importlib.util.spec_from_file_location("alfworld_export_confirmed", _script)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
export_confirmed = _module.export_confirmed


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_export_requires_confirmed_repeat_and_preserves_supporting_script(tmp_path: Path):
    root = tmp_path / "campaign/hypotheses/H005"
    root.mkdir(parents=True)
    submission = tmp_path / "submission"
    (submission / "results").mkdir(parents=True)
    best_path = tmp_path / "campaign/best/best.json"
    best_path.parent.mkdir(parents=True)
    _write_json(best_path, {"candidate_id": "R0", "val_by_id": {f"val:{i:04d}": 0 for i in range(18)}})
    package = root / "candidate/skills/alfworld-strategy"
    (package / "scripts").mkdir(parents=True)
    skill = package / "SKILL.md"
    helper = package / "scripts/safe_send.py"
    skill.write_text("---\nname: alfworld-strategy\ndescription: Test.\n---\n\nBody\n")
    helper.write_text("print('guard')\n")
    _write_json(root / "candidate_manifest.json", {
        "candidate_id": "H005", "skill_path": str(skill), "helper_path": str(helper),
        "skill_sha256": hashlib.sha256(skill.read_bytes()).hexdigest(),
        "helper_sha256": hashlib.sha256(helper.read_bytes()).hexdigest(),
    })
    _write_json(root / "val_gate.json", {"decision": "PROVISIONAL_ACCEPT", "samples": 18})
    (root / "val-rollout").mkdir()
    _write_json(root / "val-rollout/rollouts.json", [{"id": f"val:{i:04d}", "hard": 1} for i in range(18)])
    _write_json(root / "val_gate.json", {"decision": "PROVISIONAL_ACCEPT", "samples": 18, "candidate_passed": 18})
    _write_json(root / "confirmation.json", {
        "decision": "REJECT_REPEAT", "baseline_passed": [16, 16], "candidate_passed": [17, 15],
    })
    with pytest.raises(RuntimeError, match="repeat-confirmed"):
        export_confirmed(root, submission)
    assert not (submission / "skills/alfworld-strategy").exists()
    _write_json(root / "confirmation.json", {
        "decision": "CONFIRMED_ACCEPT", "baseline_passed": [16, 15], "candidate_passed": [17, 17],
    })
    exported = export_confirmed(root, submission)
    assert exported["candidate_id"] == "H005"
    assert exported["skill_path"] == "skills/alfworld-strategy/SKILL.md"
    assert (submission / "skills/alfworld-strategy/SKILL.md").read_bytes() == skill.read_bytes()
    assert (submission / "skills/alfworld-strategy/scripts/safe_send.py").read_bytes() == helper.read_bytes()
    assert json.loads(best_path.read_text())["candidate_id"] == "H005"
    assert (best_path.parent / "best-R0-before-H005.json").is_file()
    assert export_confirmed(root, submission) == exported
