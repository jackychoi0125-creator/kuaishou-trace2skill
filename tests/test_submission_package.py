from __future__ import annotations

import json
import runpy
from pathlib import Path
from types import SimpleNamespace

from skillopt.envs.harbor_pi.rollout import _target_model_id
from skillopt.envs.harbor_pi.rollout import HarborKitRollout
from skillopt.envs.harbor_pi.skill_packager import package_skill
from skillopt.envs.harbor_pi.trace_converter import atif_to_conversation, convert_record
from trace2skill.campaign import run_candidate_sequence
from trace2skill.contrastive_reflect import _provenance, compact_conversation
from trace2skill.patch_selection import filter_patch_pool


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


def test_skill_packager_uses_skill_frontmatter_name(tmp_path: Path):
    path = package_skill(
        "---\nname: alfworld-strategy\ndescription: Use for ALFWorld text action tasks.\n---\n\nNo learned strategy yet.",
        tmp_path,
    )
    assert path == tmp_path / "alfworld-strategy/SKILL.md"


def test_alfworld_harbor_adapter_keeps_official_split_and_family(tmp_path: Path):
    kit = Path(__file__).resolve().parents[2] / "benchmarks/alfworld-v2-kit"
    if not (kit / "benchmark/splits/split_manifest.json").is_file():
        return
    runner = HarborKitRollout(kit, tmp_path / "jobs", concurrent=1)
    assert runner.benchmark == "alfworld"
    assert runner._bench_name("train") == "alfworld-train"
    trace = {"schema_version": "ATIF-v1.8", "steps": [{"step_id": 1, "source": "user", "message": "Find object"}]}
    row = convert_record(
        {"case_id": "train__0000", "reward": 1, "trace": trace, "execution_error": True},
        tmp_path / "converted", task_type="pick_clean_then_place_in_recep", benchmark="alfworld",
    )
    assert row["id"] == "train:0000"
    assert row["execution_error"] is True
    assert row["task_type"] == "alfworld/pick_clean_then_place_in_recep"
    assert row["task_description"].endswith("pick_clean_then_place_in_recep")


def test_candidate_sequence_continues_after_rejection():
    observed = []

    def run_one(candidate_id: str) -> dict:
        observed.append(candidate_id)
        return {"decision": "REJECT", "generation_tokens": 5}

    results = run_candidate_sequence(["C001", "C002"], run_one, token_budget=20)
    assert observed == ["C001", "C002"]
    assert len(results) == 2


def test_optimizer_compaction_retains_parallel_burst_outcome():
    conversation = [{"role": "tool", "content": f"result {i}"} for i in range(100)]
    conversation[50]["content"] = '{"won": true, "done": true}'
    compact = compact_conversation(conversation)
    assert len(compact) < 30
    assert any('"won": true' in row.get("content", "") for row in compact)
    assert compact[-1]["content"] == "result 99"
    assert any("parallel results omitted" in row.get("content", "") for row in compact)


def test_reflect_provenance_discards_unprovided_case_ids():
    patch = {"patch": {"edits": [{"op": "append", "content": "Keep actions sequential.",
                                  "source_case_ids": ["train:0010", "val:0001"],
                                  "success_counterexamples": ["train:0001", "test:0001"],
                                  "regression_risk": "May add extra checks."}]}}
    output = _provenance(patch, "failure", ["train:0010"], ["train:0001"])
    edit = output["patch"]["edits"][0]
    assert edit["source_case_ids"] == ["train:0010"]
    assert edit["success_counterexamples"] == ["train:0001"]
    assert edit["regression_risk"] == "May add extra checks."


def test_terminal_model_error_is_not_treated_as_task_failure(tmp_path: Path):
    trace = {"schema_version": "ATIF-v1.8", "steps": [
        {"step_id": 1, "source": "user", "message": "Train task"},
        {"step_id": 2, "source": "agent", "message": "Trying a tool", "tool_calls": [
            {"tool_call_id": "c1", "function_name": "bash", "arguments": {"command": "true"}}
        ]},
        {"step_id": 3, "source": "agent", "extra": {"stop_reason": "error", "error": "Connection error."}},
    ]}
    row = convert_record({"case_id": "train__0030", "reward": 0, "input_tokens": 100,
                          "output_tokens": 20, "trace": trace}, tmp_path, benchmark="alfworld")
    assert row["terminal_model_error"] is True
    assert row["model_unavailable"] is False
    assert row["fail_reason"] == "Connection error."


def test_risk_filter_rejects_case_id_in_skill_body():
    edit = {"op": "append", "content": "For train:0036 use a fixed route.",
            "source_case_ids": ["train:0036"], "success_counterexamples": ["train:0038"],
            "applicability": "Two object placement", "non_applicability": "Other object counts and task types",
            "expected_effect": "Fewer actions"}
    accepted, rejected = filter_patch_pool([{"source_type": "failure", "patch": {"edits": [edit]}}])
    assert not accepted
    assert "benchmark_case_id_in_skill_content" in rejected[0]["reasons"]


def test_risk_filter_restores_stable_id_after_native_merge():
    edit = {"op": "append", "content": "When carrying one item, place it before taking another.",
            "source_case_ids": ["train:0034"], "success_counterexamples": ["train:0038"],
            "applicability": "Two item tasks", "non_applicability": "Single item tasks and tasks without carrying",
            "expected_effect": "Fewer invalid take actions"}
    accepted, rejected = filter_patch_pool([{"source_type": "failure", "edits": [edit]}])
    assert not rejected
    assert accepted[0]["edit"]["patch_id"].startswith("p-")


def test_risk_filter_catches_unsupported_invalid_action_cost_claim():
    edit = {"op": "append", "content": "Search nearby surfaces before containers.",
            "source_case_ids": ["train:0001"], "source_type": "success",
            "applicability": "When looking for a loose object",
            "non_applicability": "When a task gives a precise object location",
            "expected_effect": "Fewer searches",
            "regression_risk": "Invalid actions will not appear in admissible_commands and thus cause no harm."}
    accepted, rejected = filter_patch_pool([{"source_type": "success", "patch": {"edits": [edit]}}])
    assert not accepted
    assert "invalid_action_cost_dismissed" in rejected[0]["reasons"]


def test_next_candidate_reuses_only_clean_matching_full_train(tmp_path: Path):
    find_reusable = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/trace2skill.py"))[
        "_prior_clean_train_rollout"
    ]
    root = tmp_path / "campaign"
    stamp = root / "harbor-jobs/C001-best-train/train/run-1"
    stamp.mkdir(parents=True)
    job = stamp / "official-job"
    job.mkdir()
    (job / "summary.json").write_text('{"n_trials": 1}')
    trace = job / "traces.jsonl"
    row = {"case_id": "train__0001", "input_tokens": 1, "output_tokens": 1,
           "execution_error": False, "trace": {"schema_version": "ATIF-v1.8", "steps": []}}
    trace.write_text(json.dumps(row) + "\n")
    (stamp / "run_request.json").write_text(json.dumps({"concurrent": 1, "max_retries": 2}))
    (stamp / "run_manifest.json").write_text(json.dumps({
        "complete": True, "split": "train", "candidate_sha256": None,
        "trace_file": str(trace), "job_dir": str(job),
    }))
    assert find_reusable(root, "C002", None, 1, 2, {"train:0001"}) == (
        "C001-best-train", trace,
    )
    assert find_reusable(root, "C002", "different-skill", 1, 2, {"train:0001"}) is None
    row["execution_error"] = True
    trace.write_text(json.dumps(row) + "\n")
    assert find_reusable(root, "C002", None, 1, 2, {"train:0001"}) is None
