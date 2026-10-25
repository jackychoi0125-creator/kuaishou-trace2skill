#!/usr/bin/env python3
"""One frozen official ALFWorld Test comparison; never feeds Test into evolution."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

SUBMISSION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUBMISSION / "scripts"))
sys.path.insert(0, str(SUBMISSION / "src"))

from run_alfworld_evolution import KIT, SUBMISSION as PACKAGE, load_local_config, private_kit_env, runtime_env, yaml_models  # noqa: E402
from skillopt.envs.harbor_pi.rollout import HarborKitRollout  # noqa: E402
from trace2skill.retry_proxy import RetryProxy  # noqa: E402


def _score(rows: list[dict], expected: set[str]) -> tuple[int, list[str]]:
    if len(rows) != len(expected) or {str(r["id"]) for r in rows} != expected:
        raise RuntimeError("official Test task IDs differ from the frozen split")
    errors = sorted(str(r["id"]) for r in rows if r.get("execution_error") or
                    r.get("model_unavailable") or r.get("terminal_model_error"))
    return sum(int(r["hard"]) for r in rows), errors


def _isolate_skill(skill: Path, root: Path, confirmed: dict) -> Path:
    """Register the frozen Round 2 Skill without any Round 1 sibling Skills."""
    candidate_skills = root / "candidate-skills"
    candidate_skill = candidate_skills / skill.parent.name
    shutil.copytree(skill.parent, candidate_skill)
    if {p.name for p in candidate_skills.iterdir()} != {"alfworld-strategy"}:
        raise RuntimeError("Round 2 Test must register only the ALFWorld Skill")
    if (hashlib.sha256((candidate_skill / "SKILL.md").read_bytes()).hexdigest() != confirmed["skill_sha256"]
            or hashlib.sha256((candidate_skill / "scripts/safe_send.py").read_bytes()).hexdigest() != confirmed["helper_sha256"]):
        raise RuntimeError("isolated final Skill package differs from the frozen Best")
    return candidate_skills


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrent", type=int, default=4)
    args = parser.parse_args()
    if args.concurrent < 1 or args.concurrent > 4:
        raise ValueError("final Test concurrency is capped at four")
    confirmed = json.loads((PACKAGE / "results/alfworld-v2-confirmed-best.json").read_text(encoding="utf-8"))
    if confirmed.get("candidate_id") != "H005" or confirmed.get("decision") != "CONFIRMED_ACCEPT":
        raise RuntimeError("Test requires the repeat-confirmed frozen H005")
    skill = PACKAGE / confirmed["skill_path"]
    helper = skill.parent / "scripts/safe_send.py"
    if hashlib.sha256(skill.read_bytes()).hexdigest() != confirmed["skill_sha256"] or hashlib.sha256(helper.read_bytes()).hexdigest() != confirmed["helper_sha256"]:
        raise RuntimeError("final Skill or helper checksum changed")
    root = PACKAGE / "results/alfworld-v2-final-test-h005-isolated"
    if root.exists():
        raise FileExistsError("final Test already started; refusing to rerun or select outcomes")
    items = json.loads((KIT / "benchmark/splits/test/items.json").read_text(encoding="utf-8"))
    expected = {str(r["id"]) for r in items}
    if len(items) != 134 or len(expected) != 134:
        raise RuntimeError("unexpected official ALFWorld v2 Test split")
    key, base_url, model_ids = load_local_config()
    models = yaml_models()
    if any(model_ids.get(name) != value for name, value in models.items()):
        raise RuntimeError("active model IDs differ from frozen configuration")
    root.mkdir(parents=True)
    candidate_skills = _isolate_skill(skill, root, confirmed)
    manifest = {
        "benchmark": "ALFWorld v2", "split": "official Test", "samples": 134,
        "candidate": "H005", "skill_sha256": confirmed["skill_sha256"],
        "target_model_id": models["deepseek-v4-flash"], "target_thinking": "off",
        "concurrent": args.concurrent, "max_harbor_retries": 2,
        "order": ["H005", "R0"], "no_test_feedback_to_optimizer": True,
        "registered_skill_names": ["alfworld-strategy"],
        "skill_package_relative_path": "candidate-skills/alfworld-strategy",
        "status": "running", "api_key_persisted": False,
    }
    (root / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    proxy = RetryProxy(base_url, key)
    proxy.start()
    try:
        private_kit_env(proxy.downstream_token, proxy.container_base_url, models["deepseek-v4-flash"])
        os.environ.update(runtime_env(proxy.downstream_token, proxy.container_base_url))
        os.environ["TRACE2SKILL_LOCAL_RETRY_PROXY"] = "1"
        runner = HarborKitRollout(KIT, root / "jobs", concurrent=args.concurrent, max_retries=2)
        candidate = runner.run_split("test", items, skill_dir=candidate_skills,
                                     out_dir=root / "candidate", candidate_id="H005-frozen-final")
        candidate_passed, candidate_errors = _score(candidate, expected)
        baseline = runner.run_split("test", items, skill_dir=None,
                                    out_dir=root / "baseline", candidate_id="R0-frozen-final")
        baseline_passed, baseline_errors = _score(baseline, expected)
    finally:
        proxy.write_metrics(root / "transport_metrics.json")
        proxy.close()
    manifest.update({"status": "complete", "candidate_passed": candidate_passed,
                     "baseline_passed": baseline_passed, "candidate_error_cases": candidate_errors,
                     "baseline_error_cases": baseline_errors,
                     "comparison": "INCONCLUSIVE_MODEL_ERRORS" if candidate_errors or baseline_errors else
                                   "CANDIDATE_HIGHER" if candidate_passed > baseline_passed else
                                   "CANDIDATE_LOWER" if candidate_passed < baseline_passed else "TIE"})
    (root / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: manifest[k] for k in ("candidate_passed", "baseline_passed", "comparison")}))


if __name__ == "__main__":
    main()
