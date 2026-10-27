#!/usr/bin/env python3
"""Evaluate a frozen LiveMath Best Skill once on the held-out official Test split."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

SUBMISSION = Path(__file__).resolve().parents[1]
KIT = Path(os.environ.get("HARBOR_KIT_ROOT", SUBMISSION.parent / "benchmarks/livemath-v1.1-kit")).resolve()
os.environ["HARBOR_KIT_ROOT"] = str(KIT)
sys.path.insert(0, str(SUBMISSION / "src"))

from run_alfworld_evolution import load_local_config, private_kit_env, runtime_env, yaml_models  # noqa: E402
from skillopt.envs.harbor_pi.rollout import HarborKitRollout  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--confirmation", type=Path, required=True,
                        help="complete paired Val result for the same frozen Skill")
    parser.add_argument("--resume", action="store_true", help="resume only the same frozen Skill and job")
    args = parser.parse_args()
    campaign, out = args.campaign.resolve(), args.out.resolve()
    state = json.loads((campaign / "best/best.json").read_text(encoding="utf-8"))
    skill_root = campaign / "best/skills"
    skill_files = sorted(skill_root.glob("*/SKILL.md"))
    if len(skill_files) != 1:
        raise RuntimeError("expected exactly one Best Skill before Test")
    skill_hash = hashlib.sha256(skill_files[0].read_bytes()).hexdigest()
    if skill_hash != state.get("skill_sha256"):
        raise RuntimeError("Best Skill differs from the frozen Val-gated bytes")
    confirmation = json.loads(args.confirmation.resolve().read_text(encoding="utf-8"))
    if (confirmation.get("frozen_skill_sha256") != skill_hash
            or int(confirmation.get("case_count", -1)) != 17
            or int(confirmation.get("best_skill_passed", -1)) <= int(confirmation.get("no_skill_passed", -1))):
        raise RuntimeError("paired Val confirmation is absent, mismatched or non-improving")
    freeze = {
        "split": "test", "best_candidate_id": state.get("candidate_id"),
        "best_skill_sha256": skill_hash, "frozen_val_accuracy": state.get("val_accuracy"),
        "target_model_role": "deepseek-v4-flash", "thinking": "off",
        "submission_mode": "final-response", "seed": 0, "concurrent": 4,
        "whole_trial_retries": 0, "selection_rule": "frozen before Test; no Test-driven updates",
        "confirmation_result": str(args.confirmation.resolve()),
    }
    freeze_path = out / "freeze.json"
    if out.exists() and any(out.iterdir()):
        if not args.resume or not freeze_path.is_file():
            raise FileExistsError(f"Test output already populated: {out}")
        if json.loads(freeze_path.read_text(encoding="utf-8")) != freeze:
            raise RuntimeError("refusing to resume Test with a changed frozen configuration")
    else:
        out.mkdir(parents=True, exist_ok=True)
        freeze_path.write_text(json.dumps(freeze, indent=2) + "\n", encoding="utf-8")

    key, base_url, ids = load_local_config()
    models = yaml_models()
    if any(ids.get(name) != value for name, value in models.items()):
        raise RuntimeError("active endpoint IDs differ from submission configuration")
    private_kit_env(key, base_url, models["deepseek-v4-flash"])
    os.environ.update(runtime_env(key, base_url))
    os.environ["TRACE2SKILL_HARBOR_CONCURRENT"] = "4"
    os.environ["TRACE2SKILL_HARBOR_MAX_RETRIES"] = "0"
    items = json.loads((KIT / "benchmark/splits/test/items.json").read_text(encoding="utf-8"))
    runner = HarborKitRollout(KIT, out / "harbor-jobs", concurrent=4, max_retries=0)
    rows = runner.run_split("test", items, skill_dir=skill_root, out_dir=out / "converted-test",
                            candidate_id="frozen-final-test")
    result = {
        "best_candidate_id": state.get("candidate_id"), "best_skill_sha256": skill_hash,
        "n_trials": len(rows), "passed": sum(int(row["hard"]) for row in rows),
        "accuracy": sum(int(row["hard"]) for row in rows) / len(rows),
        "execution_error_trials": sum(bool(row.get("execution_error")) for row in rows),
        "note": "Official Test result is terminal evidence; it is never passed to Reflect, Select or Update.",
    }
    (out / "final_test_result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
