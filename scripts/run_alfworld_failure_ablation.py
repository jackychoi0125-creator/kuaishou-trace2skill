#!/usr/bin/env python3
"""Evaluate one previously generated ALFWorld failure patch on official Train.

This is a controlled ablation of saved SkillOpt output. It never calls Kimi,
reads Val/Test traces, or updates the competition Best Skill.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import sys
from pathlib import Path

SUBMISSION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUBMISSION / "src"))
sys.path.insert(0, str(SUBMISSION / "scripts"))

from run_alfworld_evolution import KIT, RUN_ROOT, load_local_config, private_kit_env, runtime_env, yaml_models  # noqa: E402
from skillopt.envs.harbor_pi.rollout import HarborKitRollout  # noqa: E402
from skillopt.envs.harbor_pi.skill_packager import package_skill  # noqa: E402
from skillopt.optimizer.skill import apply_patch_with_report  # noqa: E402


def main() -> None:
    campaign = RUN_ROOT / "campaign"
    ablation = campaign / "ablations/A001-failure-mechanics"
    source = campaign / "C001/reflect/raw-patches.json"
    initial = (campaign / "best/best_skill.md").read_text(encoding="utf-8")
    best = json.loads((campaign / "best/best.json").read_text(encoding="utf-8"))
    if best.get("candidate_id") != "R0" or best.get("skill_enabled"):
        raise RuntimeError("A001 is defined against the original no-skill Best only")
    raw = json.loads(source.read_text(encoding="utf-8"))
    edits = [e for group in raw if group.get("source_type") == "failure"
             for e in (group.get("patch") or {}).get("edits", [])
             if e.get("patch_id") == "p-92a2fc20fc79"]
    if len(edits) != 1:
        raise RuntimeError("saved failure patch p-92a2fc20fc79 is missing or ambiguous")
    selected = {"reasoning": "Controlled ablation of saved failure-derived SkillOpt edit", "edits": edits}
    candidate, report = apply_patch_with_report(initial, selected)
    placeholder = "No benchmark-derived strategies have been learned yet. Use the agent's normal reasoning and the environment feedback."
    candidate = candidate.replace(placeholder + "\n\n", "").replace(placeholder, "")
    ablation.mkdir(parents=True, exist_ok=True)
    skill_path = package_skill(candidate, ablation / "candidate/skills")
    candidate_sha = hashlib.sha256(skill_path.read_bytes()).hexdigest()
    manifest_path = ablation / "candidate_manifest.json"
    manifest = {
        "candidate_id": "A001-failure-mechanics", "source_candidate": "C001",
        "source_patch_id": edits[0]["patch_id"], "source_case_ids": edits[0].get("source_case_ids"),
        "additional_skill_generation_tokens": 0, "candidate_skill": str(skill_path),
        "candidate_sha256": candidate_sha, "best_candidate_id": "R0",
        "update_report": report, "test_executed": False,
    }
    if manifest_path.is_file() and json.loads(manifest_path.read_text(encoding="utf-8")).get("candidate_sha256") != candidate_sha:
        raise RuntimeError("existing A001 candidate has different bytes; refusing to overwrite")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ablation / "selected_patch.json").write_text(json.dumps(selected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ablation / "candidate.diff").write_text("".join(difflib.unified_diff(
        initial.splitlines(keepends=True), candidate.splitlines(keepends=True),
        fromfile="R0-optimizer-seed", tofile="A001-failure-mechanics",
    )), encoding="utf-8")

    key, base_url, model_ids = load_local_config()
    active_models = yaml_models()
    if any(model_ids.get(name) != value for name, value in active_models.items()):
        raise RuntimeError("model IDs differ from the active public configuration")
    private_kit_env(key, base_url, active_models["deepseek-v4-flash"])
    os.environ.update(runtime_env(key, base_url))
    items = json.loads((KIT / "benchmark/splits/train/items.json").read_text(encoding="utf-8"))
    runner = HarborKitRollout(KIT, campaign / "harbor-jobs", concurrent=1, max_retries=2)
    candidate_rows = runner.run_split(
        "train", items, skill_dir=ablation / "candidate/skills",
        out_dir=ablation / "candidate-train", candidate_id="A001-failure-mechanics",
    )
    candidate_by_id = {str(row["id"]): int(row["hard"]) for row in candidate_rows}
    if len(candidate_by_id) != len(items):
        raise RuntimeError("official candidate Train split is incomplete")
    comparisons = []
    for cid in ("C001", "C002"):
        path = campaign / cid / "train-current-best/rollouts.json"
        baseline = json.loads(path.read_text(encoding="utf-8"))
        before = {str(row["id"]): int(row["hard"]) for row in baseline}
        if before.keys() != candidate_by_id.keys():
            raise RuntimeError("candidate and no-skill Train task IDs differ")
        comparisons.append({
            "baseline_job": f"{cid}-best-train", "baseline_passed": sum(before.values()),
            "candidate_passed": sum(candidate_by_id.values()),
            "fixed_cases": sorted(i for i in before if not before[i] and candidate_by_id[i]),
            "regressed_cases": sorted(i for i in before if before[i] and not candidate_by_id[i]),
        })
    errors = [row["id"] for row in candidate_rows if row.get("execution_error") or row.get("model_unavailable") or row.get("terminal_model_error")]
    result = {
        "candidate_id": "A001-failure-mechanics", "official_train_samples": len(candidate_rows),
        "candidate_passed": sum(candidate_by_id.values()),
        "candidate_accuracy": sum(candidate_by_id.values()) / len(candidate_rows),
        "candidate_error_case_ids": errors, "comparisons": comparisons,
        "val_executed": False, "test_executed": False,
    }
    (ablation / "train_screen.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"stage": "train_screen_complete", "candidate_passed": result["candidate_passed"], "errors": len(errors)}))


if __name__ == "__main__":
    main()
