#!/usr/bin/env python3
"""Offline paired behavior and cost analysis of a completed official Val repeat."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from alfworld_hypothesis_analysis import ROOT, analyze_trial


def _cases(jobs: Path, skill_bytes: bytes) -> dict[str, dict]:
    rows = [analyze_trial(p, skill_bytes) for p in jobs.glob("**/val__*/") if (p / "result.json").is_file()]
    by_id = {r["case_id"]: r for r in rows}
    if len(rows) != 18 or len(by_id) != 18:
        raise RuntimeError("paired analysis requires all 18 official Val trials")
    return by_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-id", default="H005")
    args = parser.parse_args()
    root = ROOT / args.candidate_id
    confirmation = json.loads((root / "confirmation.json").read_text(encoding="utf-8"))
    label = confirmation.get("attempt_label") or "initial"
    suffix = "" if label == "initial" else f"-{label}"
    manifest = json.loads((root / "candidate_manifest.json").read_text(encoding="utf-8"))
    skill_bytes = Path(manifest["skill_path"]).read_bytes()
    if hashlib.sha256(skill_bytes).hexdigest() != manifest["skill_sha256"]:
        raise RuntimeError("frozen Skill checksum mismatch")
    jobs = root / f"confirmation-jobs{suffix}"
    candidate = _cases(jobs / f"{args.candidate_id}-repeat{suffix}", skill_bytes)
    baseline = _cases(jobs / f"R0-repeat{suffix}", b"nonexistent-skill-body")
    if set(candidate) != set(baseline) or sum(r["passed"] for r in candidate.values()) != confirmation["candidate_passed"][1] or sum(r["passed"] for r in baseline.values()) != confirmation["baseline_passed"][1]:
        raise RuntimeError("trial scores differ from official paired confirmation")
    paired = [{
        "case_id": case_id,
        "candidate_passed": candidate[case_id]["passed"],
        "baseline_passed": baseline[case_id]["passed"],
        "candidate_loaded_step": candidate[case_id]["skill_body_read_step"],
        "candidate_helper_calls": candidate[case_id]["helper_call_count"],
        "candidate_official_actions": candidate[case_id]["official_action_count"],
        "baseline_official_actions": baseline[case_id]["official_action_count"],
        "candidate_output_tokens": candidate[case_id]["output_tokens"],
        "baseline_output_tokens": baseline[case_id]["output_tokens"],
        "candidate_model_errors": candidate[case_id]["model_error_events"],
        "baseline_model_errors": baseline[case_id]["model_error_events"],
    } for case_id in sorted(candidate)]
    result = {
        "candidate_id": args.candidate_id, "attempt_label": label,
        "decision": confirmation["decision"], "samples": 18,
        "candidate_passed": sum(r["candidate_passed"] for r in paired),
        "baseline_passed": sum(r["baseline_passed"] for r in paired),
        "fixed_cases": [r["case_id"] for r in paired if r["candidate_passed"] and not r["baseline_passed"]],
        "regressed_cases": [r["case_id"] for r in paired if r["baseline_passed"] and not r["candidate_passed"]],
        "candidate_loaded_count": sum(r["candidate_loaded_step"] is not None for r in paired),
        "candidate_helper_use_count": sum(r["candidate_helper_calls"] > 0 for r in paired),
        "candidate_official_actions": sum(r["candidate_official_actions"] for r in paired),
        "baseline_official_actions": sum(r["baseline_official_actions"] for r in paired),
        "candidate_output_tokens": sum(int(r["candidate_output_tokens"] or 0) for r in paired),
        "baseline_output_tokens": sum(int(r["baseline_output_tokens"] or 0) for r in paired),
        "cases": paired,
    }
    path = root / f"confirmation_behavior{suffix}.json"
    if path.exists():
        raise FileExistsError("paired behavior analysis already exists")
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "cases"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
