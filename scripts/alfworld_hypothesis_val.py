#!/usr/bin/env python3
"""Run the official full Val gate for a Train-qualified ALFWorld hypothesis."""
from __future__ import annotations

import argparse
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-id", choices=("H001", "H002", "H003", "H004", "H005", "H006"), default="H001")
    args = parser.parse_args()
    candidate_id = args.candidate_id
    root = RUN_ROOT / "campaign/hypotheses" / candidate_id
    diagnostic = json.loads((root / "diagnostic_result.json").read_text(encoding="utf-8"))
    if not diagnostic.get("passes_predeclared_train_gate"):
        raise RuntimeError(f"{candidate_id} failed its frozen Train gate; Val run prohibited")
    manifest = json.loads((root / "candidate_manifest.json").read_text(encoding="utf-8"))
    if hashlib.sha256(Path(manifest["skill_path"]).read_bytes()).hexdigest() != manifest["skill_sha256"]:
        raise RuntimeError("candidate SKILL.md hash mismatch")
    if manifest.get("helper_path") and hashlib.sha256(Path(manifest["helper_path"]).read_bytes()).hexdigest() != manifest["helper_sha256"]:
        raise RuntimeError("candidate Skill script hash mismatch")
    best = json.loads((RUN_ROOT / "campaign/best/best.json").read_text(encoding="utf-8"))
    if best.get("candidate_id") != "R0" or best.get("skill_enabled"):
        raise RuntimeError(f"{candidate_id} Val comparator must remain the no-skill R0 baseline")
    key, base_url, model_ids = load_local_config()
    configured = yaml_models()
    if any(model_ids.get(name) != value for name, value in configured.items()):
        raise RuntimeError("model IDs differ from active configuration")
    private_kit_env(key, base_url, configured["deepseek-v4-flash"])
    os.environ.update(runtime_env(key, base_url))
    val_items = json.loads((KIT / "benchmark/splits/val/items.json").read_text(encoding="utf-8"))
    runner = HarborKitRollout(KIT, root / "val-jobs", concurrent=1, max_retries=2)
    candidate_rows = runner.run_split(
        "val", val_items, skill_dir=Path(manifest["skill_path"]).parent.parent,
        out_dir=root / "val-rollout", candidate_id=candidate_id,
    )
    by_id = {str(r["id"]): int(r["hard"]) for r in candidate_rows}
    before = {str(k): int(v) for k,v in best["val_by_id"].items()}
    if before.keys() != by_id.keys() or len(by_id) != len(val_items):
        raise RuntimeError("Val case IDs differ from official R0 baseline")
    errors = [str(r["id"]) for r in candidate_rows if r.get("execution_error") or r.get("model_unavailable") or r.get("terminal_model_error")]
    passed = sum(by_id.values())
    decision = "INCONCLUSIVE_MODEL_ERRORS" if errors else "PROVISIONAL_ACCEPT" if passed > sum(before.values()) else "REJECT"
    report = {
        "candidate_id": candidate_id, "baseline_passed": sum(before.values()), "candidate_passed": passed,
        "samples": len(by_id), "candidate_accuracy": passed / len(by_id),
        "fixed_cases": sorted(i for i in before if not before[i] and by_id[i]),
        "regressed_cases": sorted(i for i in before if before[i] and not by_id[i]),
        "candidate_model_or_execution_error_cases": errors,
        "decision": decision, "best_updated": False, "test_executed": False,
    }
    (root / "val_gate.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"candidate_id": candidate_id, "passed": passed, "baseline": sum(before.values()),
                      "errors": len(errors), "decision": decision}))


if __name__ == "__main__":
    main()
