from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("run_livemath_evolution", SCRIPTS / "run_livemath_evolution.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
sys.path.remove(str(SCRIPTS))


def test_official_job_requires_complete_independent_comparison(tmp_path: Path):
    jobs = tmp_path / "jobs"
    run = jobs / "run-1"
    trial = run / "lm202511-1__trial"
    trial.mkdir(parents=True)
    (trial / "result.json").write_text('{}')
    (run / "summary.json").write_text(json.dumps({"n_trials": 1}))
    (run / "official-comparison.json").write_text(json.dumps({
        "complete": True, "all_grades_match": True, "errors": 0,
    }))
    assert module._official_job(jobs, 1) == run
    with pytest.raises(RuntimeError, match="incomplete or mismatched"):
        module._official_job(jobs, 2)
    (run / "official-comparison.json").write_text(json.dumps({
        "complete": True, "all_grades_match": False, "errors": 0,
    }))
    with pytest.raises(RuntimeError, match="incomplete or mismatched"):
        module._official_job(jobs, 1)
