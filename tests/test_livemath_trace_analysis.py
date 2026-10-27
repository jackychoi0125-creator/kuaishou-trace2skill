from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/livemath_trace_analysis.py"
spec = importlib.util.spec_from_file_location("livemath_trace_analysis", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_official_final_response_is_scored_as_wrong_label_not_non_delivery(tmp_path: Path):
    trial = tmp_path / "lm202602-22__trial"
    for folder in ("verifier", "agent", "artifacts/bench/answers/lm202602-22"):
        (trial / folder).mkdir(parents=True)
    (trial / "result.json").write_text(json.dumps({
        "task_name": "lm202602-22", "verifier_result": {"rewards": {"reward": 0.0}},
        "agent_result": {"n_input_tokens": 100, "n_output_tokens": 20, "n_cache_tokens": 50},
    }))
    (trial / "verifier/metrics.json").write_text(json.dumps({
        "answer_status": "valid", "parsed_answer": "B",
    }))
    (trial / "agent/submission.json").write_text(json.dumps({
        "finish_reason": "stop", "response_bytes": 9,
    }))
    (trial / "agent/trajectory.json").write_text(json.dumps({
        "schema_version": "ATIF-v1.8", "steps": [{"source": "agent", "message": "\\boxed{B}"}],
    }))
    (trial / "artifacts/bench/answers/lm202602-22/final-response.txt").write_text("\\boxed{B}")
    row = module.analyze_trial(trial)
    assert row["case_id"] == "202602:22"
    assert row["cause"] == "scored_wrong_label"
    assert row["boxed_label_count"] == 1
    assert row["cached_tokens_subset_of_input"] == 50
