#!/usr/bin/env python3
"""Run a frozen official Train subset for one packaged Skill hypothesis."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

SUBMISSION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUBMISSION / "src"))
sys.path.insert(0, str(SUBMISSION / "scripts"))

from run_alfworld_evolution import KIT, RUN_ROOT, load_local_config, private_kit_env, runtime_env, yaml_models  # noqa: E402
from alfworld_hypothesis_analysis import analyze_trial  # noqa: E402
from skillopt.envs.harbor_pi.trace_converter import terminal_model_error  # noqa: E402


def _completed_trials(job: Path, expected: set[str]) -> list[dict]:
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in job.glob("*/result.json")]
    if len(rows) != len(expected) or {str(r.get("task_name", "")).replace("__", ":") for r in rows} != expected:
        raise RuntimeError("official diagnostic job does not contain the exact frozen Train cases")
    if not all(r.get("finished_at") and ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward") is not None for r in rows):
        raise RuntimeError("official diagnostic job has unfinished or unscored trials")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-id", choices=("H001", "H002", "H003", "H004", "H005", "H006"), default="H001")
    args = parser.parse_args()
    candidate_id = args.candidate_id
    root = RUN_ROOT / "campaign/hypotheses" / candidate_id
    plan = json.loads((root / "diagnostic_plan.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "candidate_manifest.json").read_text(encoding="utf-8"))
    if hashlib.sha256(Path(manifest["skill_path"]).read_bytes()).hexdigest() != manifest["skill_sha256"]:
        raise RuntimeError("candidate SKILL.md hash mismatch")
    if manifest.get("helper_path") and hashlib.sha256(Path(manifest["helper_path"]).read_bytes()).hexdigest() != manifest["helper_sha256"]:
        raise RuntimeError("candidate Skill script hash mismatch")
    expected = set(plan["case_ids"])
    if len(expected) != 14:
        raise RuntimeError("frozen subset must have 14 unique Train IDs")
    skill_dir = Path(manifest["skill_path"]).parent.parent
    jobs_root = root / "diagnostic-jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    existing = [p for p in jobs_root.glob("*") if p.is_dir()]
    if len(existing) > 1:
        raise RuntimeError("multiple diagnostic Harbor jobs exist; refusing to pick one")
    key, base_url, model_ids = load_local_config()
    configured = yaml_models()
    if any(model_ids.get(name) != value for name, value in configured.items()):
        raise RuntimeError("model IDs differ from active configuration")
    private_kit_env(key, base_url, configured["deepseek-v4-flash"])
    env = runtime_env(key, base_url)
    if not existing:
        cmd = [str(KIT / "run.sh"), "--bench", "alfworld-train", "--n", "14", "--seed", "141",
               "--reasoning", "off", "--concurrent", "1", "--model-id", configured["deepseek-v4-flash"],
               "--base-url", base_url, "--skills-dir", str(skill_dir), "--jobs-dir", str(jobs_root)]
        with (root / "diagnostic_runner.log").open("w", encoding="utf-8") as log:
            subprocess.run(cmd, cwd=KIT.parent, env=env, stdout=log, stderr=subprocess.STDOUT,
                           timeout=4 * 3600, check=False)
        existing = [p for p in jobs_root.glob("*") if p.is_dir()]
    if len(existing) != 1:
        raise RuntimeError("official Harbor diagnostic job directory not found")
    job = existing[0]
    trials = _completed_trials(job, expected)
    py = KIT / "workspace/.venv/bin/python"
    summary = job / "summary.json"
    if not summary.is_file():
        r = subprocess.run([str(py), str(KIT / "results/summarize.py"), "--job", str(job)],
                           cwd=KIT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
        if r.returncode or not summary.is_file():
            raise RuntimeError("official Harbor summary recovery failed")
    trace = job / "traces.jsonl"
    if not trace.is_file():
        r = subprocess.run([str(py), str(KIT / "results/export_traces.py"), "--job", str(job), "--output", str(trace)],
                           cwd=KIT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
        if r.returncode or not trace.is_file():
            raise RuntimeError("official Harbor ATIF export failed")
    records = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(records) != len(expected) or {str(r.get("case_id", "")).replace("__", ":") for r in records} != expected:
        raise RuntimeError("official ATIF case IDs differ from the frozen subset")
    by_id = {str(r["task_name"]).replace("__", ":"): int(((r.get("verifier_result") or {}).get("rewards") or {}).get("reward") > 0)
             for r in trials}
    baseline = {}
    for cid in ("C001", "C002"):
        rows = json.loads((RUN_ROOT / "campaign" / cid / "train-current-best/rollouts.json").read_text(encoding="utf-8"))
        baseline[cid] = {str(r["id"]): int(r["hard"]) for r in rows if str(r["id"]) in expected}
    stable_success = {i for i in expected if baseline["C001"][i] and baseline["C002"][i]}
    regression = sorted(i for i in stable_success if not by_id[i])
    errors = sorted({str(r.get("case_id", "")).replace("__", ":") for r in records
                     if r.get("execution_error") or (int(r.get("input_tokens") or 0) == 0 and int(r.get("output_tokens") or 0) == 0)
                     or terminal_model_error(r.get("trace") or {})})
    passed = sum(by_id.values())
    helper_adoption_cases = None
    if candidate_id in {"H004", "H005", "H006"}:
        skill_bytes = Path(manifest["skill_path"]).read_bytes()
        helper_adoption_cases = sorted(
            str(row["case_id"]) for trial in job.glob("train__*/")
            if (row := analyze_trial(trial, skill_bytes))["helper_call_count"] > 0
        )
    adoption_passed = helper_adoption_cases is None or len(helper_adoption_cases) >= 5
    result = {
        "candidate_id": candidate_id, "official_train_samples": 14, "official_passed": passed,
        "official_accuracy": passed / 14, "baseline_passed": {cid: sum(b.values()) for cid,b in baseline.items()},
        "case_results": by_id, "stable_success_regressions": regression,
        "model_or_execution_error_cases": errors,
        "helper_adoption_cases": helper_adoption_cases,
        "passes_predeclared_train_gate": passed >= 12 and len(regression) <= 1 and not errors and adoption_passed,
        "official_job": str(job), "official_trace": str(trace), "val_executed": False, "test_executed": False,
    }
    (root / "diagnostic_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"candidate_id": candidate_id, "passed": passed, "regressions": len(regression),
                      "errors": len(errors), "helper_adoption": len(helper_adoption_cases) if helper_adoption_cases is not None else None,
                      "gate": result["passes_predeclared_train_gate"]}))


if __name__ == "__main__":
    main()
