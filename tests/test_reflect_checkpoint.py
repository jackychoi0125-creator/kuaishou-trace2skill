from __future__ import annotations

import json

import pytest

from skillopt.gradient import reflect
from skillopt.model import openai_compatible_backend as backend
from trace2skill.contrastive_reflect import run_contrastive_reflect


def test_reflect_resume_skips_metered_completed_batches(tmp_path, monkeypatch):
    results = [
        {"id": "f1", "hard": 0, "task_description": "Benchmark: spreadsheetbench; task family: general"},
        {"id": "f2", "hard": 0, "task_description": "Benchmark: spreadsheetbench; task family: general"},
        {"id": "s1", "hard": 1, "task_description": "Benchmark: spreadsheetbench; task family: general"},
    ]
    predictions = tmp_path / "predictions"
    for row in results:
        path = predictions / row["id"] / "conversation.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps([{"role": "user", "content": "task"}, {"role": "assistant", "content": "answer"}]))

    calls = []

    def analyst(skill, batch, prediction_dir, **kwargs):
        calls.append(batch[0]["id"])
        backend.tracker.record("analyst", 2, 3)
        return {"patch": {"edits": [{"op": "add", "content": "Check the relevant precondition."}]}}

    monkeypatch.setattr(reflect, "run_error_analyst_minibatch", analyst)
    monkeypatch.setattr(reflect, "run_success_analyst_minibatch", analyst)
    backend.reset_token_tracker()
    kwargs = dict(results=results, prediction_dir=predictions, patches_dir=tmp_path / "reflect/patches",
                  skill_content="seed", batch_size=1, edit_budget=1)
    first = run_contrastive_reflect(**kwargs)
    second = run_contrastive_reflect(**kwargs)
    assert len(first) == len(second) == 3
    assert calls == ["f1", "f2", "s1"]
    assert (tmp_path / "reflect/reflect-batches.json").is_file()
    with pytest.raises(RuntimeError, match="different Train input"):
        run_contrastive_reflect(**{**kwargs, "skill_content": "different seed"})
