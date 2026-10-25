#!/usr/bin/env python3
"""Optional observation-token guard for public ALFWorld actions.

An action needs the unpredictable token from the *previous* helper result.
Consequently, actions preplanned in one Pi response cannot all consume the
same observation. This wraps only the public bridge; it never changes the
game, official transcript, Pi, or scorer.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

_QID = re.compile(r"(?:train|val|test):\d{4}\Z")
_WORK = Path("/bench/work")


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


def _token_file(qid: str, work_dir: Path) -> Path:
    return work_dir / f".alfworld-skill-token-{qid.replace(':', '-')}.json"


def _read_token(qid: str, work_dir: Path) -> dict:
    try:
        value = json.loads(_token_file(qid, work_dir).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) and value.get("qid") == qid else {}
    except (OSError, ValueError):
        return {}


def _new_token(qid: str, state: dict, work_dir: Path) -> str:
    token = secrets.token_hex(12)
    path = _token_file(qid, work_dir)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"qid": qid, "steps": state.get("steps"), "token": token}), encoding="utf-8")
    tmp.replace(path)
    return token


def guarded_action(qid: str, action: str, token: str | None = None, *, work_dir: Path = _WORK) -> dict:
    if not _QID.fullmatch(qid):
        raise ValueError("expected an official train/val/test episode ID")
    if action != "observe" and (not action or len(action) > 200):
        raise ValueError("expected one short public ALFWorld action")
    work_dir.mkdir(parents=True, exist_ok=True)
    with (work_dir / ".alfworld-skill-action.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        state = _bridge("status", qid)
        if action == "observe":
            return {**state, "next_action_token": _new_token(qid, state, work_dir)}
        current = _read_token(qid, work_dir)
        if not token or token != current.get("token") or state.get("steps") != current.get("steps"):
            # A stale token never sends an action. Return the latest state so
            # the agent can make a new decision in its next response.
            fresh = (current.get("token") if state.get("steps") == current.get("steps") else None)
            if not fresh:
                fresh = _new_token(qid, state, work_dir)
            return {**state, "skill_guard": "skipped_stale_observation", "next_action_token": fresh}
        if state.get("won") or state.get("done"):
            return {**state, "skill_guard": "skipped_episode_finished", "next_action_token": token}
        if action not in (state.get("admissible_commands") or []):
            return {**state, "skill_guard": "skipped_non_admissible", "next_action_token": token}
        if action.startswith("go to ") and _previous_actions(qid) == [action, action]:
            return {**state, "skill_guard": "skipped_third_identical_navigation", "next_action_token": token}
        result = _bridge("send", qid, action)
        return {**result, "next_action_token": _new_token(qid, result, work_dir)}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) not in (2, 3):
        print("usage: safe_send.py <episode-id> observe | <episode-id> '<action>' <token>", file=sys.stderr)
        return 2
    try:
        result = guarded_action(args[0], args[1], args[2] if len(args) == 3 else None)
    except (ValueError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
        print(f"Skill action guard error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
