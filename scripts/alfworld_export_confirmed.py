#!/usr/bin/env python3
"""Export only a repeat-confirmed ALFWorld Skill to the standard submission path."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

SUBMISSION = Path(__file__).resolve().parents[1]
RUN_ROOT = SUBMISSION / "results/alfworld-v2-20261020-evolution"


def export_confirmed(root: Path, submission: Path) -> dict:
    confirmation = json.loads((root / "confirmation.json").read_text(encoding="utf-8"))
    if confirmation.get("decision") != "CONFIRMED_ACCEPT":
        raise RuntimeError("candidate has no repeat-confirmed official Val improvement")
    gate = json.loads((root / "val_gate.json").read_text(encoding="utf-8"))
    if gate.get("decision") != "PROVISIONAL_ACCEPT" or gate.get("samples") != 18:
        raise RuntimeError("candidate lacks a complete 18-case official Val gate")
    manifest = json.loads((root / "candidate_manifest.json").read_text(encoding="utf-8"))
    source = Path(manifest["skill_path"])
    helper = Path(manifest["helper_path"])
    if hashlib.sha256(source.read_bytes()).hexdigest() != manifest["skill_sha256"]:
        raise RuntimeError("frozen candidate Skill checksum mismatch")
    if hashlib.sha256(helper.read_bytes()).hexdigest() != manifest["helper_sha256"]:
        raise RuntimeError("frozen helper checksum mismatch")
    best_path = root.parent.parent / "best/best.json"
    prior_best = json.loads(best_path.read_text(encoding="utf-8"))
    if prior_best.get("candidate_id") not in ("R0", manifest["candidate_id"]):
        raise RuntimeError("a different candidate already owns Round 2 Best")
    candidate_rows = json.loads((root / "val-rollout/rollouts.json").read_text(encoding="utf-8"))
    candidate_by_id = {str(r["id"]): int(r["hard"]) for r in candidate_rows}
    if len(candidate_rows) != 18 or set(candidate_by_id) != set(prior_best["val_by_id"]):
        raise RuntimeError("candidate Val rollout is not the exact official 18-case split")
    if sum(candidate_by_id.values()) != gate.get("candidate_passed"):
        raise RuntimeError("candidate Val rollout and gate score disagree")
    destination = submission / "skills/alfworld-strategy"
    if destination.exists():
        same = ((destination / "SKILL.md").is_file()
                and hashlib.sha256((destination / "SKILL.md").read_bytes()).hexdigest() == manifest["skill_sha256"]
                and (destination / "scripts/safe_send.py").is_file()
                and hashlib.sha256((destination / "scripts/safe_send.py").read_bytes()).hexdigest() == manifest["helper_sha256"])
        if not same:
            raise FileExistsError("a different ALFWorld Skill is already exported; refusing to overwrite it")
    else:
        shutil.copytree(source.parent, destination)
    result = {
        "candidate_id": manifest["candidate_id"],
        "decision": confirmation["decision"],
        "skill_path": "skills/alfworld-strategy/SKILL.md",
        "skill_sha256": manifest["skill_sha256"],
        "helper_sha256": manifest["helper_sha256"],
        "baseline_passed": confirmation["baseline_passed"],
        "candidate_passed": confirmation["candidate_passed"],
        "test_executed": False,
    }
    out = submission / "results/alfworld-v2-confirmed-best.json"
    if out.exists():
        prior = json.loads(out.read_text(encoding="utf-8"))
        if prior != result:
            raise FileExistsError("a different confirmed Best manifest already exists")
    else:
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if prior_best.get("candidate_id") == "R0":
        archive = best_path.with_name(f"best-R0-before-{manifest['candidate_id']}.json")
        if archive.exists() and json.loads(archive.read_text(encoding="utf-8")) != prior_best:
            raise FileExistsError("R0 Best archive differs from current baseline")
        if not archive.exists():
            archive.write_text(json.dumps(prior_best, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        new_best = {
            "candidate_id": manifest["candidate_id"], "val_accuracy": sum(candidate_by_id.values()) / 18,
            "skill_sha256": manifest["skill_sha256"], "skill_enabled": True,
            "val_by_id": candidate_by_id,
            "val_quality": {"execution_error_trials": 0, "zero_response_trials": 0, "terminal_model_error_trials": 0},
            "source": "official Harbor full Val and balanced repeat confirmation",
            "harbor_candidate_id": manifest["candidate_id"],
            "confirmation_path": str(root / "confirmation.json"),
            "exported_skill_path": "skills/alfworld-strategy/SKILL.md",
        }
        temp = best_path.with_suffix(".tmp")
        temp.write_text(json.dumps(new_best, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(best_path)
    elif prior_best.get("skill_sha256") != manifest["skill_sha256"]:
        raise RuntimeError("Best candidate ID matches but Skill checksum differs")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-id", choices=("H004", "H005", "H006"), required=True)
    args = parser.parse_args()
    root = RUN_ROOT / "campaign/hypotheses" / args.candidate_id
    result = export_confirmed(root, SUBMISSION)
    print(json.dumps({k: result[k] for k in ("candidate_id", "decision", "skill_sha256")}))


if __name__ == "__main__":
    main()
