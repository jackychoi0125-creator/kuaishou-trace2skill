#!/usr/bin/env python3
"""Optional Skill-side guard for public ALFWorld bridge actions.

Uses only the official public bridge and authoritative action transcript. It
does not inspect the game engine, reference routes, private state, or scorer.
The fixed Pi agent must opt in by invoking this Skill script for each action.
"""
from __future__ import annotations

import fcntl
import json
import re
import subprocess
import sys
from pathlib import Path

_QID = re.compile(r"(?:train|val|test):\d{4}\Z")


def _bridge(operation: str, qid: str, command: str | None = None) -> dict:
    argv = ["bridge.sh", operation, qid]
    if command is not None:
        argv.append(command)
    result = subprocess.run(argv, capture_output=True, text=True, timeout=90, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[:500] or f"bridge {operation} exited {result.returncode}")
    state = json.loads(result.stdout)
    if not isinstance(state, dict):
        raise RuntimeError("bridge returned a non-object state")
    return state


def _previous_actions(qid: str) -> list[str]:
    transcript = Path("/bench/answers") / qid / "trajectory.jsonl"
    if not transcript.is_file():
        return []
    actions = []
    for line in transcript.read_text(encoding="utf-8").splitlines()[-2:]:
        try:
            actions.append(str(json.loads(line).get("command") or ""))
        except ValueError:
            return []
    return actions


def _guard_reason(state: dict, previous: list[str], action: str) -> str | None:
    if state.get("won") or state.get("done"):
        return "skipped_episode_finished"
    if action not in (state.get("admissible_commands") or []):
        return "skipped_non_admissible"
    if action.startswith("go to ") and previous == [action, action]:
        return "skipped_third_identical_navigation"
    return None


def guarded_send(qid: str, action: str, *, lock_path: Path = Path("/bench/work/.alfworld-skill-action.lock")) -> dict:
    if not _QID.fullmatch(qid):
        raise ValueError("expected an official train/val/test episode ID")
    if not action or len(action) > 200:
        raise ValueError("expected one short public ALFWorld action")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as stream:
        # Serializes concurrent invocations of this Skill helper. Every action
        # is rechecked against current public state after acquiring the lock.
        fcntl.flock(stream, fcntl.LOCK_EX)
        state = _bridge("status", qid)
        reason = _guard_reason(state, _previous_actions(qid), action)
        if reason:
            return {**state, "skill_guard": reason, "proposed_action": action}
        return _bridge("send", qid, action)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: safe_send.py <episode-id> '<one admissible action>'", file=sys.stderr)
        return 2
    try:
        result = guarded_send(args[0], args[1])
    except (ValueError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        print(f"Skill action guard error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
