from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from skillopt.envs.harbor_pi.rollout import _target_model_id
from skillopt.envs.harbor_pi.skill_packager import package_skill
from skillopt.envs.harbor_pi.trace_converter import atif_to_conversation, convert_record
from trace2skill.campaign import run_candidate_sequence


def test_vendored_model_config_resolves_inside_submission():
    assert _target_model_id().startswith("ep-")


def test_atif_trace_conversion_preserves_tool_evidence(tmp_path: Path):
    trace = {
        "schema_version": "ATIF-v1.8",
        "steps": [
            {"step_id": 1, "source": "user", "message": "untrusted task text"},
            {
                "step_id": 2,
                "source": "agent",
                "tool_calls": [{"tool_call_id": "c1", "function_name": "python", "arguments": {"cmd": "print(1)"}}],
                "observation": {"results": [{"source_call_id": "c1", "content": "1"}]},
            },
        ],
    }
    conversation = atif_to_conversation(trace)
    assert "UNTRUSTED USER TRACE DATA" in conversation[0]["content"]
    assert conversation[1]["type"] == "tool_call"
    converted = convert_record({"case_id": "case-1", "reward": 1, "trace": trace}, tmp_path)
    assert converted["hard"] == 1
    assert json.loads((tmp_path / "predictions/case-1/conversation.json").read_text()) == conversation


def test_skill_packager_emits_standard_frontmatter(tmp_path: Path):
    path = package_skill("# Workflow\n\nInspect and validate the workbook.", tmp_path)
    content = path.read_text()
    assert content.startswith("---\nname: spreadsheet-workflow\n")
    assert "description:" in content.split("---", 2)[1]


def test_candidate_sequence_continues_after_rejection():
    observed = []

    def run_one(candidate_id: str) -> dict:
        observed.append(candidate_id)
        return {"decision": "REJECT", "generation_tokens": 5}

    results = run_candidate_sequence(["C001", "C002"], run_one, token_budget=20)
    assert observed == ["C001", "C002"]
    assert len(results) == 2
