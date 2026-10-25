from __future__ import annotations

from pathlib import Path

from trace2skill import alfworld_safe_send as guard


def test_action_guard_preserves_admissible_single_step_and_blocks_redundancy():
    state = {"won": False, "done": False, "admissible_commands": ["go to shelf 1", "open shelf 1"]}
    assert guard._guard_reason(state, [], "go to shelf 1") is None
    assert guard._guard_reason(state, ["go to shelf 1", "go to shelf 1"], "go to shelf 1") == "skipped_third_identical_navigation"
    assert guard._guard_reason(state, [], "go to shelf 2") == "skipped_non_admissible"
    assert guard._guard_reason({**state, "won": True}, [], "open shelf 1") == "skipped_episode_finished"


def test_guarded_send_uses_current_public_status_before_official_send(tmp_path: Path, monkeypatch):
    calls = []

    def bridge(operation, qid, action=None):
        calls.append((operation, qid, action))
        if operation == "status":
            return {"won": False, "done": False, "admissible_commands": ["go to shelf 1"]}
        return {"won": False, "done": False, "observation": "You arrive at shelf 1."}

    monkeypatch.setattr(guard, "_bridge", bridge)
    monkeypatch.setattr(guard, "_previous_actions", lambda qid: [])
    lock = tmp_path / "guard.lock"
    assert guard.guarded_send("train:0013", "go to shelf 1", lock_path=lock)["observation"] == "You arrive at shelf 1."
    assert calls == [("status", "train:0013", None), ("send", "train:0013", "go to shelf 1")]
    calls.clear()
    assert guard.guarded_send("train:0013", "go to shelf 2", lock_path=lock)["skill_guard"] == "skipped_non_admissible"
    assert calls == [("status", "train:0013", None)]
