#!/usr/bin/env python3
"""Summarize official ALFWorld diagnostic behavior without a model call."""
from __future__ import annotations

import argparse
import collections
import hashlib
import itertools
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "results/alfworld-v2-20261020-evolution/campaign/hypotheses"


def analyze_trial(trial: Path, skill_bytes: bytes) -> dict:
    result = json.loads((trial / "result.json").read_text(encoding="utf-8"))
    trace = json.loads((trial / "agent/trajectory.json").read_text(encoding="utf-8"))
    actions_file = next(trial.glob("artifacts/bench/answers/*/trajectory.jsonl"), None)
    actions = [str(json.loads(line).get("command") or "") for line in actions_file.read_text(encoding="utf-8").splitlines()] if actions_file else []
    max_repeat_go = max((sum(1 for _ in group) for action, group in itertools.groupby(actions)
                         if action.startswith("go to ")), default=0)
    read_step = None
    max_sends_per_model_step = 0
    max_helper_calls_per_model_step = 0
    helper_call_count = 0
    guard_skip_reasons: collections.Counter[str] = collections.Counter()
    model_error_events = 0
    for step in trace.get("steps") or []:
        extra = step.get("extra") or {}
        if extra.get("stop_reason") == "error" or extra.get("error"):
            model_error_events += 1
        sends = 0
        helper_calls_this_step = 0
        results = {r.get("source_call_id"): r for r in ((step.get("observation") or {}).get("results") or [])}
        for call in step.get("tool_calls") or []:
            args = call.get("arguments") or {}
            observed_content = str(results.get(call.get("tool_call_id"), {}).get("content") or "")
            if call.get("function_name") == "read" and str(args.get("path") or "").endswith("/alfworld-strategy/SKILL.md"):
                if skill_bytes.decode("utf-8") in observed_content:
                    read_step = str(step.get("step_id"))
            if call.get("function_name") == "bash":
                command = str(args.get("command") or "")
                if "/alfworld-strategy/SKILL.md" in command and skill_bytes.decode("utf-8") in observed_content:
                    read_step = str(step.get("step_id"))
                sends += len(re.findall(r"bridge\.sh\s+send\s+", command))
                helper_calls_this_step += command.count("safe_send.py")
                if "safe_send.py" in command:
                    for reason in re.findall(r'"skill_guard"\s*:\s*"([a-z_]+)"', observed_content):
                        guard_skip_reasons[reason] += 1
        max_sends_per_model_step = max(max_sends_per_model_step, sends)
        helper_call_count += helper_calls_this_step
        max_helper_calls_per_model_step = max(max_helper_calls_per_model_step, helper_calls_this_step)
    metrics = trace.get("final_metrics") or {}
    return {
        "case_id": str(result.get("task_name") or "").replace("__", ":"),
        "passed": int((((result.get("verifier_result") or {}).get("rewards") or {}).get("reward") or 0) > 0),
        "skill_body_read_step": read_step,
        "official_action_count": len(actions),
        "max_identical_go_streak": max_repeat_go,
        "max_bridge_sends_in_one_model_step": max_sends_per_model_step,
        "max_helper_calls_in_one_model_step": max_helper_calls_per_model_step,
        "helper_call_count": helper_call_count,
        "guard_skip_reasons": dict(guard_skip_reasons),
        "model_error_events": model_error_events,
        "input_tokens": metrics.get("total_prompt_tokens"),
        "output_tokens": metrics.get("total_completion_tokens"),
        "cached_tokens_subset_of_input": metrics.get("total_cached_tokens"),
        "execution_error": bool(result.get("exception_info")),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-id", choices=("H001", "H002", "H003", "H004", "H005", "H006"), required=True)
    args = parser.parse_args()
    root = ROOT / args.candidate_id
    manifest = json.loads((root / "candidate_manifest.json").read_text(encoding="utf-8"))
    skill_bytes = Path(manifest["skill_path"]).read_bytes()
    if hashlib.sha256(skill_bytes).hexdigest() != manifest["skill_sha256"]:
        raise RuntimeError("candidate skill SHA256 mismatch")
    jobs = [p for p in (root / "diagnostic-jobs").glob("*") if p.is_dir()]
    if len(jobs) != 1:
        raise RuntimeError("expected exactly one official diagnostic job")
    cases = sorted((analyze_trial(p, skill_bytes) for p in jobs[0].glob("train__*/")
                    if (p / "result.json").is_file()), key=lambda row: row["case_id"])
    plan = json.loads((root / "diagnostic_plan.json").read_text(encoding="utf-8"))
    if {r["case_id"] for r in cases} != set(plan["case_ids"]):
        raise RuntimeError("diagnostic trial IDs do not match frozen plan")
    summary = {
        "candidate_id": args.candidate_id,
        "cases": cases,
        "loaded_case_count": sum(r["skill_body_read_step"] is not None for r in cases),
        "cases_with_multi_send_step": sum(r["max_bridge_sends_in_one_model_step"] > 1 for r in cases),
        "cases_with_three_or_more_repeated_go": sum(r["max_identical_go_streak"] >= 3 for r in cases),
        "cases_invoking_guard_helper": sum(r["helper_call_count"] > 0 for r in cases),
        "model_error_events": sum(r["model_error_events"] for r in cases),
        "target_input_tokens_including_cache": sum(int(r["input_tokens"] or 0) for r in cases),
        "target_output_tokens": sum(int(r["output_tokens"] or 0) for r in cases),
        "target_cached_tokens_subset_of_input": sum(int(r["cached_tokens_subset_of_input"] or 0) for r in cases),
    }
    (root / "diagnostic_behavior.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "cases"}))


if __name__ == "__main__":
    main()
