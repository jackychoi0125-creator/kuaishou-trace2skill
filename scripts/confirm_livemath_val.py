#!/usr/bin/env python3
"""One frozen, paired LiveMath Val confirmation; never feeds Val into SkillOpt."""
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
    parser.add_argument("--resume", action="store_true", help="resume only the same frozen pair")
    args = parser.parse_args()
    campaign, out = args.campaign.resolve(), args.out.resolve()
    best_state = json.loads((campaign / "best/best.json").read_text(encoding="utf-8"))
    skill_root = campaign / "best/skills"
    skill_files = sorted(skill_root.glob("*/SKILL.md"))
    if len(skill_files) != 1:
        raise RuntimeError("expected exactly one frozen Best Skill")
    skill_hash = hashlib.sha256(skill_files[0].read_bytes()).hexdigest()
    if skill_hash != best_state.get("skill_sha256"):
        raise RuntimeError("Best Skill bytes changed since the gate decision")

    key, base_url, ids = load_local_config()
    models = yaml_models()
    if any(ids.get(name) != value for name, value in models.items()):
        raise RuntimeError("active endpoint IDs differ from submission configuration")
    private_kit_env(key, base_url, models["deepseek-v4-flash"])
    os.environ.update(runtime_env(key, base_url))
    os.environ["TRACE2SKILL_HARBOR_CONCURRENT"] = "4"
    os.environ["TRACE2SKILL_HARBOR_MAX_RETRIES"] = "0"
    items = json.loads((KIT / "benchmark/splits/val/items.json").read_text(encoding="utf-8"))
    freeze = {
        "split": "val", "case_count": len(items), "model_role": "deepseek-v4-flash target",
        "thinking": "off", "submission_mode": "final-response", "seed": 0,
        "concurrent": 4, "whole_trial_retries": 0,
        "best_candidate_id": best_state.get("candidate_id"), "best_skill_sha256": skill_hash,
        "order": ["no_skill", "frozen_best_skill"],
    }
    freeze_path = out / "freeze.json"
    if out.exists() and any(out.iterdir()):
        if not args.resume or not freeze_path.is_file():
            raise FileExistsError(f"confirmation output already populated: {out}")
        if json.loads(freeze_path.read_text(encoding="utf-8")) != freeze:
            raise RuntimeError("refusing to resume a changed confirmation pair")
    else:
        out.mkdir(parents=True, exist_ok=True)
        freeze_path.write_text(json.dumps(freeze, indent=2) + "\n", encoding="utf-8")
    runner = HarborKitRollout(KIT, out / "harbor-jobs", concurrent=4, max_retries=0)
    baseline = runner.run_split("val", items, skill_dir=None, out_dir=out / "no-skill",
                                candidate_id="frozen-confirm-no-skill")
    candidate = runner.run_split("val", items, skill_dir=skill_root, out_dir=out / "best-skill",
                                 candidate_id="frozen-confirm-best-skill")
    a = {str(row["id"]): int(row["hard"]) for row in baseline}
    b = {str(row["id"]): int(row["hard"]) for row in candidate}
    if set(a) != set(b) or len(a) != len(items):
        raise RuntimeError("official Val case sets differ")
    paired = {
        "no_skill_passed": sum(a.values()), "best_skill_passed": sum(b.values()),
        "case_count": len(a),
        "fixed_cases": sorted(k for k in a if a[k] == 0 and b[k] == 1),
        "regressed_cases": sorted(k for k in a if a[k] == 1 and b[k] == 0),
        "no_skill_by_id": a, "best_skill_by_id": b,
        "frozen_skill_sha256": skill_hash,
    }
    (out / "paired_result.json").write_text(json.dumps(paired, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in paired.items() if k in ("no_skill_passed", "best_skill_passed", "case_count")}))


if __name__ == "__main__":
    main()
