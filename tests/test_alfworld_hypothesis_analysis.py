from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def test_full_skill_read_via_bash_is_counted(tmp_path: Path):
    script = Path(__file__).resolve().parents[1] / "scripts/alfworld_hypothesis_analysis.py"
    spec = importlib.util.spec_from_file_location("alfworld_hypothesis_analysis", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    trial = tmp_path / "train__0000__fixture"
    (trial / "agent").mkdir(parents=True)
    answer = trial / "artifacts/bench/answers/train:0000"
    answer.mkdir(parents=True)
    (answer / "trajectory.jsonl").write_text('{"command":"go to shelf 1"}\n')
    (trial / "result.json").write_text(json.dumps({
        "task_name": "train__0000", "verifier_result": {"rewards": {"reward": 1}},
    }))
    skill = b"---\nname: alfworld-strategy\ndescription: Use for ALFWorld.\n---\n\nA full rule.\n"
    trace = {"steps": [{"step_id": "2", "tool_calls": [{
        "tool_call_id": "c1", "function_name": "bash",
        "arguments": {"command": "cat /root/.agents/skills/alfworld-strategy/SKILL.md"},
    }], "observation": {"results": [{"source_call_id": "c1", "content": skill.decode()}]}}],
             "final_metrics": {"total_prompt_tokens": 10, "total_completion_tokens": 3,
                               "total_cached_tokens": 4}}
    (trial / "agent/trajectory.json").write_text(json.dumps(trace))
    row = module.analyze_trial(trial, skill)
    assert row["skill_body_read_step"] == "2"
    assert row["input_tokens"] == 10
    assert row["cached_tokens_subset_of_input"] == 4
