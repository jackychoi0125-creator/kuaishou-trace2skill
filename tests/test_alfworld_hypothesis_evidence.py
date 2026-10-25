from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def test_observation_evidence_matches_tool_results_by_call_id(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[1] / "scripts/alfworld_hypothesis_candidate.py"
    spec = importlib.util.spec_from_file_location("alfworld_hypothesis_candidate", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "RUN_ROOT", tmp_path)
    trial = tmp_path / "campaign/harbor-jobs/J/train/batch/job/train__0013__fixture"
    answers = trial / "artifacts/bench/answers/train:0013"
    answers.mkdir(parents=True)
    (trial / "agent").mkdir()
    (trial / "result.json").write_text(json.dumps({"verifier_result": {"rewards": {"reward": 0}}}))
    (answers / "trajectory.jsonl").write_text('{"command":"go to shelf 1"}\n{"command":"inventory"}\n')
    trace = {"steps": [{"step_id": "7", "tool_calls": [
        {"tool_call_id": "a", "arguments": {"command": 'bridge.sh send train:0013 "go to shelf 1"'}},
        {"tool_call_id": "b", "arguments": {"command": 'bridge.sh send train:0013 "inventory"'}},
    ], "observation": {"results": [
        {"source_call_id": "b", "content": json.dumps({"observation": "You carry nothing.", "admissible_commands": []})},
        {"source_call_id": "a", "content": json.dumps({"observation": "You arrive at shelf 1.", "admissible_commands": ["look"]})},
    ]}}]}
    (trial / "agent/trajectory.json").write_text(json.dumps(trace))
    evidence = module._public_observation_evidence("train:0013", "J")
    assert evidence["selected_observations"] == [
        {"step_id": "7", "action": "go to shelf 1", "observation": "You arrive at shelf 1.",
         "won": False, "done": False, "admissible_count": 1},
        {"step_id": "7", "action": "inventory", "observation": "You carry nothing.",
         "won": False, "done": False, "admissible_count": 0},
    ]
