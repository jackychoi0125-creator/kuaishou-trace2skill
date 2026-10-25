#!/usr/bin/env python3
"""Balanced official Val repeat for one Train-qualified provisional candidate.

The first Val candidate run must already beat R0. This command then runs one
unchanged candidate Val and one fresh no-skill Val, in that fixed order. It
does not generate or edit a Skill and does not read reference answers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

SUBMISSION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUBMISSION / "scripts"))
sys.path.insert(0, str(SUBMISSION / "src"))

from run_alfworld_evolution import KIT, RUN_ROOT, load_local_config, private_kit_env, runtime_env, yaml_models  # noqa: E402
from skillopt.envs.harbor_pi.rollout import HarborKitRollout  # noqa: E402
from trace2skill.retry_proxy import RetryProxy  # noqa: E402


def _scores(rows: list[dict], expected_ids: set[str]) -> tuple[dict[str, int], list[str]]:
    by_id = {str(r["id"]): int(r["hard"]) for r in rows}
    if set(by_id) != expected_ids or len(rows) != len(expected_ids):
        raise RuntimeError("official Val task IDs differ from frozen comparator")
    errors = sorted(str(r["id"]) for r in rows if r.get("execution_error") or
                    r.get("model_unavailable") or r.get("terminal_model_error"))
    return by_id, errors


def _paired(before: dict[str, int], after: dict[str, int]) -> dict:
    return {
        "fixed_cases": sorted(i for i in before if not before[i] and after[i]),
        "regressed_cases": sorted(i for i in before if before[i] and not after[i]),
    }


def confirmation_decision(b1: int, b2: int, c1: int, c2: int, *, has_errors: bool) -> str:
    if has_errors:
        return "INCONCLUSIVE_MODEL_ERRORS"
    if c1 > b1 and c2 > b2:
        return "CONFIRMED_ACCEPT"
    if c2 < b2:
        return "REJECT_REPEAT"
    return "INCONCLUSIVE_VARIATION"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-id", choices=("H001", "H002", "H003", "H004", "H005", "H006"), required=True)
    parser.add_argument("--attempt-label", default="", help="Unique label for a full paired rerun after a documented infrastructure error")
    parser.add_argument("--retry-proxy", action="store_true", help="Keep upstream credential on host and retry upstream HTTP 429 without changing Pi requests")
    args = parser.parse_args()
    if args.attempt_label and (not args.attempt_label.replace("-", "").replace("_", "").isalnum() or len(args.attempt_label) > 32):
        raise ValueError("attempt label must be short alphanumeric text with '-' or '_'")
    root = RUN_ROOT / "campaign/hypotheses" / args.candidate_id
    if (root / "confirmation.json").exists():
        raise FileExistsError("confirmation already exists; refusing to rerun or select the best repeat")
    if args.attempt_label:
        priors = [json.loads(p.read_text(encoding="utf-8")) for p in root.glob("confirmation_attempt*_inconclusive.json")]
        if not any(p.get("http_status") == 429 and p.get("full_18_case_score_claimed") is False for p in priors):
            raise RuntimeError("labeled retry is permitted only after an incomplete HTTP 429 attempt")
    gate = json.loads((root / "val_gate.json").read_text(encoding="utf-8"))
    if gate["decision"] != "PROVISIONAL_ACCEPT":
        raise RuntimeError("candidate did not provisionally beat the official no-skill Val baseline")
    manifest = json.loads((root / "candidate_manifest.json").read_text(encoding="utf-8"))
    skill = Path(manifest["skill_path"])
    if hashlib.sha256(skill.read_bytes()).hexdigest() != manifest["skill_sha256"]:
        raise RuntimeError("candidate Skill changed since first Val")
    if manifest.get("helper_path") and hashlib.sha256(Path(manifest["helper_path"]).read_bytes()).hexdigest() != manifest["helper_sha256"]:
        raise RuntimeError("candidate Skill script changed since first Val")
    best = json.loads((RUN_ROOT / "campaign/best/best.json").read_text(encoding="utf-8"))
    if best.get("candidate_id") != "R0" or best.get("skill_enabled"):
        raise RuntimeError("confirmation comparator is no longer the no-skill R0")
    first_baseline = {str(i): int(v) for i, v in best["val_by_id"].items()}
    expected = set(first_baseline)
    first_rows = json.loads((root / "val-rollout/rollouts.json").read_text(encoding="utf-8"))
    first_candidate, first_errors = _scores(first_rows, expected)
    if first_errors or sum(first_candidate.values()) != gate["candidate_passed"]:
        raise RuntimeError("first Val rollout does not match its provisional gate")
    key, base_url, model_ids = load_local_config()
    models = yaml_models()
    if any(model_ids.get(name) != value for name, value in models.items()):
        raise RuntimeError("active model IDs differ from local configuration")
    items = json.loads((KIT / "benchmark/splits/val/items.json").read_text(encoding="utf-8"))
    suffix = f"-{args.attempt_label}" if args.attempt_label else ""
    if any((root / f"{name}{suffix}").exists() for name in
           ("confirmation-jobs", "confirmation-candidate", "confirmation-baseline")):
        raise FileExistsError("confirmation attempt already has artifacts; choose a new label after documenting the error")
    proxy = RetryProxy(base_url, key) if args.retry_proxy else None
    if proxy:
        proxy.start()
    try:
        active_key = proxy.downstream_token if proxy else key
        active_url = proxy.container_base_url if proxy else base_url
        private_kit_env(active_key, active_url, models["deepseek-v4-flash"])
        os.environ.update(runtime_env(active_key, active_url))
        if proxy:
            os.environ["TRACE2SKILL_LOCAL_RETRY_PROXY"] = "1"
        runner = HarborKitRollout(KIT, root / f"confirmation-jobs{suffix}", concurrent=1, max_retries=2)
        candidate_rows = runner.run_split("val", items, skill_dir=skill.parent.parent,
                                          out_dir=root / f"confirmation-candidate{suffix}", candidate_id=args.candidate_id + "-repeat" + suffix)
        candidate_repeat, candidate_errors = _scores(candidate_rows, expected)
        baseline_rows = runner.run_split("val", items, skill_dir=None,
                                         out_dir=root / f"confirmation-baseline{suffix}", candidate_id="R0-repeat" + suffix)
        baseline_repeat, baseline_errors = _scores(baseline_rows, expected)
    finally:
        if proxy:
            proxy.write_metrics(root / f"confirmation_proxy_metrics{suffix}.json")
            proxy.close()
    b1, b2 = sum(first_baseline.values()), sum(baseline_repeat.values())
    c1, c2 = sum(first_candidate.values()), sum(candidate_repeat.values())
    decision = confirmation_decision(b1, b2, c1, c2,
                                     has_errors=bool(baseline_errors or candidate_errors))
    report = {
        "candidate_id": args.candidate_id, "candidate_skill_sha256": manifest["skill_sha256"],
        "attempt_label": args.attempt_label or "initial",
        "transport_retry_proxy": bool(proxy),
        "transport_retry_metrics_path": str(root / f"confirmation_proxy_metrics{suffix}.json") if proxy else None,
        "prior_inconclusive_attempts": sorted(p.name for p in root.glob("confirmation_attempt*_inconclusive.json")),
        "samples_per_run": len(expected), "baseline_passed": [b1, b2], "candidate_passed": [c1, c2],
        "baseline_mean_accuracy": (b1 + b2) / (2 * len(expected)),
        "candidate_mean_accuracy": (c1 + c2) / (2 * len(expected)),
        "first_run_pair": _paired(first_baseline, first_candidate),
        "repeat_pair": _paired(baseline_repeat, candidate_repeat),
        "baseline_repeat_error_cases": baseline_errors,
        "candidate_repeat_error_cases": candidate_errors,
        "decision": decision, "test_executed": False,
    }
    (root / "confirmation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"candidate_id": args.candidate_id, "baseline": [b1, b2],
                      "candidate": [c1, c2], "decision": decision}))


if __name__ == "__main__":
    main()
