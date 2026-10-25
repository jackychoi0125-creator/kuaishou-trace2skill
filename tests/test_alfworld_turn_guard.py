from __future__ import annotations

from pathlib import Path

from trace2skill import alfworld_turn_guard as guard


def test_single_use_observation_token_prevents_preplanned_batch(tmp_path: Path, monkeypatch):
    state = {"steps": 0, "won": False, "done": False, "admissible_commands": ["go to shelf 1"]}
    sent = []

    def bridge(operation, qid, action=None):
        if operation == "send":
            sent.append(action)
            state["steps"] += 1
            state["observation"] = "You arrive at shelf 1."
        return dict(state)

    monkeypatch.setattr(guard, "_bridge", bridge)
    monkeypatch.setattr(guard, "_previous_actions", lambda qid: [])
    first = guard.guarded_action("train:0029", "observe", work_dir=tmp_path)
    token = first["next_action_token"]
    accepted = guard.guarded_action("train:0029", "go to shelf 1", token, work_dir=tmp_path)
    stale = guard.guarded_action("train:0029", "go to shelf 1", token, work_dir=tmp_path)
    assert sent == ["go to shelf 1"]
    assert stale["skill_guard"] == "skipped_stale_observation"
    assert accepted["next_action_token"] == stale["next_action_token"]
    assert accepted["next_action_token"] != token


def test_invalid_action_does_not_spend_token(tmp_path: Path, monkeypatch):
    state = {"steps": 0, "won": False, "done": False, "admissible_commands": ["open shelf 1"]}
    sent = []

    def bridge(operation, qid, action=None):
        if operation == "send":
            sent.append(action)
            state["steps"] += 1
        return dict(state)

    monkeypatch.setattr(guard, "_bridge", bridge)
    monkeypatch.setattr(guard, "_previous_actions", lambda qid: [])
    token = guard.guarded_action("train:0030", "observe", work_dir=tmp_path)["next_action_token"]
    rejected = guard.guarded_action("train:0030", "open shelf 2", token, work_dir=tmp_path)
    assert rejected["skill_guard"] == "skipped_non_admissible"
    assert rejected["next_action_token"] == token
    guard.guarded_action("train:0030", "open shelf 1", token, work_dir=tmp_path)
    assert sent == ["open shelf 1"]
