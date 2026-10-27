#!/usr/bin/env python3
"""Reproduce the bounded LiveMath Train→SkillOpt→Val campaign with the official Kit."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SUBMISSION = Path(__file__).resolve().parents[1]
KIT = Path(os.environ.get("HARBOR_KIT_ROOT", SUBMISSION.parent / "benchmarks/livemath-v1.1-kit")).resolve()
os.environ["HARBOR_KIT_ROOT"] = str(KIT)

from run_alfworld_evolution import load_local_config, private_kit_env, runtime_env, yaml_models  # noqa: E402


def _official_job(jobs: Path, expected: int) -> Path | None:
    if not jobs.is_dir():
        return None
    runs = [p for p in jobs.iterdir() if p.is_dir() and (p / "summary.json").is_file()]
    if not runs:
        return None
    if len(runs) != 1:
        raise RuntimeError(f"expected one official Harbor run under {jobs}")
    run = runs[0]
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    comparison_path = run / "official-comparison.json"
    comparison = json.loads(comparison_path.read_text(encoding="utf-8")) if comparison_path.is_file() else {}
    if (int(summary.get("n_trials", -1)) != expected or len(list(run.glob("*/result.json"))) != expected
            or comparison.get("complete") is not True or comparison.get("all_grades_match") is not True
            or int(comparison.get("errors", -1)) != 0):
        raise RuntimeError(f"incomplete or mismatched official Harbor result under {jobs}")
    return run


def _baseline(split: str, root: Path, env: dict[str, str], key: str) -> Path:
    expected = 35 if split == "train" else 17
    jobs = KIT / "workspace/runs" / f"livemath-{split}" / "baseline-r0-20261027"
    run = _official_job(jobs, expected)
    if run is None:
        if jobs.exists() and any(jobs.iterdir()):
            raise RuntimeError(f"existing incomplete {split} jobs; inspect and recover with official Kit before continuing")
        log = root / f"{split}_baseline.log"
        with log.open("w", encoding="utf-8") as stream:
            proc = subprocess.run(
                [str(KIT / "run.sh"), "--bench", f"livemath-{split}", "--concurrent", "4",
                 "--reasoning", "off", "--submission-mode", "final-response", "--seed", "0",
                 "--jobs-dir", str(jobs)], cwd=KIT, env=env, stdout=stream,
                stderr=subprocess.STDOUT, check=False,
            )
        # The Kit keeps credentials private, but scrub any unexpected failure
        # text before retaining the wrapper's log.
        content = log.read_text(encoding="utf-8", errors="replace")
        log.write_text(content.replace(key, "[REDACTED]"), encoding="utf-8")
        if proc.returncode:
            raise RuntimeError(f"official {split} baseline failed (exit={proc.returncode}); inspect {log}")
        run = _official_job(jobs, expected)
        if run is None:
            raise RuntimeError(f"official {split} baseline has no summary")
    trace = root / f"{split}-baseline-r0-atif.jsonl"
    if not trace.is_file():
        exporter = KIT / "results/export_traces.py"
        proc = subprocess.run([str(KIT / "workspace/.venv/bin/python"), str(exporter),
                               "--job", str(run), "--output", str(trace)],
                              cwd=KIT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              text=True, check=False)
        if proc.returncode or not trace.is_file():
            raise RuntimeError(f"official {split} ATIF export failed")
    records = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(records) != expected:
        raise RuntimeError(f"official {split} trace count differs from split")
    return trace


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, default=SUBMISSION / "results/livemath-v1.1-20261027")
    parser.add_argument("--max-candidates", type=int, default=2)
    parser.add_argument("--token-budget", type=int, default=500000)
    parser.add_argument("--minibatch-size", type=int, default=4)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    root = args.run_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not (KIT / "workspace/.venv/bin/harbor").is_file():
        raise RuntimeError("official LiveMath Kit setup is incomplete")
    key, base_url, ids = load_local_config()
    models = yaml_models()
    if any(ids.get(name) != value for name, value in models.items()):
        raise RuntimeError("active endpoint IDs differ from the submitted model configuration")
    private_kit_env(key, base_url, models["deepseek-v4-flash"])
    env = runtime_env(key, base_url)
    env["TRACE2SKILL_HARBOR_CONCURRENT"] = "4"
    env["TRACE2SKILL_HARBOR_MAX_RETRIES"] = "0"  # Official LiveMath Kit disables whole-trial retry.
    env["TRACE2SKILL_INITIAL_NO_SKILL"] = "1"
    blank = SUBMISSION / "src/skillopt/envs/livemath/skills/blank.md"
    env["TRACE2SKILL_INITIAL_SKILL"] = str(blank)
    train = _baseline("train", root, env, key)
    val = _baseline("val", root, env, key)
    command = [sys.executable, str(SUBMISSION / "scripts/trace2skill.py"), "search",
               "--run-root", str(root / "campaign"), "--initial-train-trace", str(train),
               "--initial-val-trace", str(val), "--initial-skill", str(blank),
               "--initial-no-skill", "--max-candidates", str(args.max_candidates),
               "--token-budget", str(args.token_budget), "--train-regression-tolerance", "0.05",
               "--minibatch-size", str(args.minibatch_size), "--edit-budget", "1"]
    if args.resume:
        command.append("--resume")
    with (root / "evolution.log").open("w", encoding="utf-8") as stream:
        proc = subprocess.run(command, cwd=SUBMISSION, env=env, stdout=stream,
                              stderr=subprocess.STDOUT, check=False)
    log = root / "evolution.log"
    log.write_text(log.read_text(encoding="utf-8", errors="replace").replace(key, "[REDACTED]"),
                   encoding="utf-8")
    if proc.returncode:
        raise RuntimeError(f"LiveMath campaign failed (exit={proc.returncode}); inspect {log}")
    print(json.dumps({"status": "complete", "campaign": str(root / "campaign"),
                      "train_trace": str(train), "val_baseline_trace": str(val)}))


if __name__ == "__main__":
    main()
