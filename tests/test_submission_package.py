from __future__ import annotations

import json
import hashlib
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from skillopt.envs.harbor_pi.rollout import _target_model_id
from skillopt.envs.harbor_pi.rollout import HarborKitRollout
from skillopt.envs.harbor_pi.skill_packager import package_skill
from skillopt.envs.harbor_pi.trace_converter import atif_to_conversation, convert_record, normalize_case_id
from skillopt.prompts import load_prompt
from trace2skill.campaign import regressed_success_counterexamples, run_candidate_sequence


def test_train_guard_flags_regressed_cited_success_even_with_neutral_net_score():
    selected = {"edits": [{"success_counterexamples": ["success-a", "success-b"]}]}
    before = {"success-a": 1, "success-b": 1, "failure-a": 0}
    after = {"success-a": 0, "success-b": 1, "failure-a": 1}
    assert sum(before.values()) == sum(after.values())
    assert regressed_success_counterexamples(selected, before, after) == ["success-a"]
    assert regressed_success_counterexamples(selected, before, before) == []
from trace2skill.contrastive_reflect import _family, _provenance, compact_conversation, recover_unique_native_patch
from trace2skill.patch_selection import filter_patch_pool


def test_livemath_export_requires_improving_frozen_pair(tmp_path: Path, monkeypatch):
    campaign = tmp_path / "campaign"
    skill = campaign / "best/skills/livemath-strategy/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: livemath-strategy\ndescription: Math MCQ.\n---\n\nCheck claims.\n")
    digest = hashlib.sha256(skill.read_bytes()).hexdigest()
    (campaign / "best/best.json").write_text(json.dumps({"candidate_id": "C002", "skill_sha256": digest}))
    confirmation = tmp_path / "paired_result.json"
    out = tmp_path / "export/SKILL.md"
    script = Path(__file__).resolve().parents[1] / "scripts/export_livemath_best.py"
    monkeypatch.setattr(sys, "argv", [str(script), "--campaign", str(campaign),
                                     "--confirmation", str(confirmation), "--out", str(out)])
    confirmation.write_text(json.dumps({"frozen_skill_sha256": digest, "case_count": 17,
                                        "no_skill_passed": 4, "best_skill_passed": 4}))
    with pytest.raises(RuntimeError, match="improving paired Val"):
        runpy.run_path(str(script), run_name="__main__")
    assert not out.exists()
    confirmation.write_text(json.dumps({"frozen_skill_sha256": digest, "case_count": 17,
                                        "no_skill_passed": 3, "best_skill_passed": 6}))
    runpy.run_path(str(script), run_name="__main__")
    assert out.read_bytes() == skill.read_bytes()


def test_optimizer_response_audit_recovers_usage_without_double_counting(tmp_path: Path):
    audit_dir = tmp_path / "optimizer-responses"
    audit_dir.mkdir()
    rows = [
        {"stage": "analyst", "usage": {"prompt_tokens": 100, "completion_tokens": 80,
          "total_tokens": 180, "reasoning_tokens": 70, "cached_tokens": 20,
          "finish_reason": "stop"}},
        {"stage": "merge", "usage": {"prompt_tokens": 50, "completion_tokens": 30,
          "total_tokens": 80, "reasoning_tokens": 25, "cached_tokens": 10,
          "finish_reason": "stop"}},
    ]
    for index, row in enumerate(rows):
        (audit_dir / f"{index}.json").write_text(json.dumps(row))
    loader = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/trace2skill.py"))[
        "response_audit_usage"
    ]
    usage = loader(tmp_path)
    assert usage["_total"]["calls"] == 2
    assert usage["_total"]["total_tokens"] == 260
    assert usage["_total"]["reasoning_tokens"] == 95
    assert usage["_total"]["cached_tokens"] == 30
    assert usage["analyst"]["total_tokens"] == 180


def test_search_resume_preserves_accepted_best_despite_initial_no_skill(tmp_path: Path):
    best_dir = tmp_path / "best"
    best_dir.mkdir()
    content = "---\nname: livemath-strategy\ndescription: Math MCQ.\n---\n\nLearned rule.\n"
    (best_dir / "best_skill.md").write_text(content)
    state = {"candidate_id": "C002", "skill_enabled": True,
             "skill_sha256": hashlib.sha256(content.encode()).hexdigest(),
             "val_accuracy": 6 / 17, "val_by_id": {"202601:1": 1}}
    (best_dir / "best.json").write_text(json.dumps(state))
    loader = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/trace2skill.py"))[
        "_search_initialize_best"
    ]
    assert loader(tmp_path, initial_skill=str(best_dir / "best_skill.md"), no_skill=True) == best_dir / "best_skill.md"
    assert json.loads((best_dir / "best.json").read_text()) == state
    broken = {**state, "skill_sha256": "0" * 64}
    (best_dir / "best.json").write_text(json.dumps(broken))
    with pytest.raises(RuntimeError, match="accepted Best state"):
        loader(tmp_path, initial_skill=str(best_dir / "best_skill.md"), no_skill=True)


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


def test_math_trace_compaction_keeps_question_and_terminal_box():
    long_answer = "opening argument\n" + "".join(
        f"middle derivation step {index} with many details\n" for index in range(500)
    ) + "\\boxed{D}"
    rows = [{"role": "user", "content": "research theorem question"},
            {"role": "assistant", "content": long_answer}]
    compacted = compact_conversation(rows, math_mode=True)
    assert compacted[0]["content"] == "research theorem question"
    assert "opening argument" in compacted[1]["content"]
    assert "\\boxed{D}" in compacted[1]["content"]
    assert "OMITTED" in compacted[1]["content"]


def test_livemath_reflect_recovers_one_exact_json_after_prose():
    body = json.dumps({"patch": {"reasoning": "Train evidence", "edits": [{"op": "append", "content": "Check hypotheses."}]}})
    recovered = recover_unique_native_patch("analysis {informal note}\n" + body, "failure")
    assert recovered is not None
    assert recovered["patch"]["edits"][0]["content"] == "Check hypotheses."
    assert recovered["source_type"] == "failure"
    assert recover_unique_native_patch(body + "\n" + body, "failure") is None


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


def test_livemath_adapter_identifies_kit_and_canonical_ids(tmp_path: Path):
    kit = tmp_path / "kit"
    split = kit / "benchmark/splits"
    split.mkdir(parents=True)
    (kit / "run.sh").write_text("#!/bin/sh\nHARBOR_ARGS='--max-retries 0'\n")
    (split / "split_manifest.json").write_text('{"dataset":"LiveMathematicianBench"}')
    runner = HarborKitRollout(kit, tmp_path / "jobs", concurrent=1)
    assert runner.benchmark == "livemath"
    assert runner.supports_max_retries is False
    assert runner._bench_name("val") == "livemath-val"
    assert normalize_case_id("lm202602-22") == "202602:22"
    assert normalize_case_id("202602:22") == "202602:22"
    trace = {"schema_version": "ATIF-v1.8", "steps": [{"step_id": 1, "source": "user",
             "message": "For a Sobolev solution of the PDE, which conclusion follows?"}]}
    row = convert_record({"case_id": "lm202602-22", "reward": 0, "trace": trace}, tmp_path,
                         benchmark="livemath")
    assert row["id"] == "202602:22"
    assert row["task_type"] == "livemath/analysis_pde"
    assert _family(row["task_description"]) == "analysis_pde"
    assert "TRAIN trajectories" in load_prompt("analyst_error", env="livemath")


def test_candidate_sequence_continues_after_rejection():
    observed = []

    def run_one(candidate_id: str) -> dict:
        observed.append(candidate_id)
        return {"decision": "REJECT", "generation_tokens": 5}

    results = run_candidate_sequence(["C001", "C002"], run_one, token_budget=20)
    assert observed == ["C001", "C002"]
    assert len(results) == 2


def test_resumed_candidate_budget_counts_only_new_generation():
    observed = []

    def run_one(candidate_id: str) -> dict:
        observed.append(candidate_id)
        return {"decision": "REJECT", "generation_tokens": 100,
                "new_generation_tokens": 0 if candidate_id == "C001" else 5}

    run_candidate_sequence(["C001", "C002"], run_one, token_budget=5)
    assert observed == ["C001", "C002"]


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


def test_risk_filter_rejects_livemath_case_id_in_skill_body():
    edit = {"op": "append", "content": "For 202512:24 choose D.",
            "source_case_ids": ["202512:24"], "success_counterexamples": ["202512:8"],
            "applicability": "Research math MCQ", "non_applicability": "All other problem settings",
            "expected_effect": "Higher score"}
    accepted, rejected = filter_patch_pool([{"source_type": "failure", "patch": {"edits": [edit]}}])
    assert not accepted
    assert "benchmark_case_id_in_skill_content" in rejected[0]["reasons"]


def test_risk_filter_rejects_fixed_livemath_answer_label():
    edit = {"op": "append", "content": "For these theorem questions, always answer: C.",
            "source_case_ids": ["202512:24"], "success_counterexamples": ["202512:8"],
            "applicability": "Research math MCQ", "non_applicability": "Questions from other domains",
            "expected_effect": "Higher score"}
    accepted, rejected = filter_patch_pool([{"source_type": "failure", "patch": {"edits": [edit]}}])
    assert not accepted
    assert "hardcoded_option_label_in_skill_content" in rejected[0]["reasons"]


def test_risk_filter_restores_stable_id_after_native_merge():
    edit = {"op": "append", "content": "When carrying one item, place it before taking another.",
            "source_case_ids": ["train:0034"], "success_counterexamples": ["train:0038"],
            "applicability": "Two item tasks", "non_applicability": "Single item tasks and tasks without carrying",
            "expected_effect": "Fewer invalid take actions"}
    accepted, rejected = filter_patch_pool([{"source_type": "failure", "edits": [edit]}])
    assert not rejected
    assert accepted[0]["edit"]["patch_id"].startswith("p-")


def test_risk_filter_checks_counterexample_against_current_train_outcome():
    edit = {"op": "append", "content": "Check the assumptions before comparing theorem strength.",
            "source_case_ids": ["case-fail"], "success_counterexamples": ["case-regressed"],
            "applicability": "Questions comparing theorem strength",
            "non_applicability": "Questions without comparable theorem statements",
            "expected_effect": "Fewer false implications"}
    accepted, rejected = filter_patch_pool(
        [{"source_type": "failure", "patch": {"edits": [edit]}}],
        train_outcomes={"case-fail": 0, "case-regressed": 0},
    )
    assert not accepted
    assert "counterexample_not_successful_in_current_train" in rejected[0]["reasons"]


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
    (stamp / "run_request.json").write_text(json.dumps({"concurrent": 1, "max_retries": None}))
    assert find_reusable(root, "C002", None, 1, 0, {"train:0001"}) == (
        "C001-best-train", trace,
    )
    (stamp / "run_request.json").write_text(json.dumps({"concurrent": 1, "max_retries": 2}))
    assert find_reusable(root, "C002", "different-skill", 1, 2, {"train:0001"}) is None
    row["execution_error"] = True
    trace.write_text(json.dumps(row) + "\n")
    assert find_reusable(root, "C002", None, 1, 2, {"train:0001"}) is None


def test_h005_frozen_train_gate_bundle_has_exact_case_alignment():
    bundle = Path(__file__).resolve().parents[1] / "results/alfworld-v2-h005-delivery"
    plan = json.loads((bundle / "train_diagnostic_plan.json").read_text())
    guard = json.loads((bundle / "train_guard_reference.json").read_text())
    result = json.loads((bundle / "train_diagnostic_result.json").read_text())
    expected = set(plan["case_ids"])
    assert len(expected) == 14
    assert expected == set(guard["case_ids"]) == set(result["case_results"])
    assert all(set(scores) == expected for scores in guard["prior_no_skill_by_case"].values())
    assert sum(result["case_results"].values()) == result["official_passed"] == 13
    assert result["passes_predeclared_train_gate"] is True


def test_livemath_optimizer_feedback_uses_only_official_train_references(tmp_path: Path):
    loader = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/trace2skill.py"))[
        "_livemath_train_labels"
    ]
    loader.__globals__["KIT"] = tmp_path
    train = tmp_path / "workspace/tasks/livemath-train.run-1/lm202602-22/tests/reference/reference.json"
    train.parent.mkdir(parents=True)
    train.write_text(json.dumps({"id": "202602:22", "correct": "D"}))
    val = tmp_path / "workspace/tasks/livemath-val.run-1/lm202602-8/tests/reference/reference.json"
    val.parent.mkdir(parents=True)
    val.write_text(json.dumps({"id": "202602:8", "correct": "A"}))
    assert loader({"202602:22"}) == {"202602:22": "D"}
    with pytest.raises(RuntimeError, match="do not cover"):
        loader({"202602:22", "202602:8"})
