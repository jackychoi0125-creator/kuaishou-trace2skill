"""Deterministic candidate-loop control, independent of Harbor/model I/O."""
from __future__ import annotations

from collections.abc import Callable


def run_candidate_sequence(
    candidate_ids: list[str], run_one: Callable[[str], dict], token_budget: int,
) -> list[dict]:
    """Continue after rejected candidates; stop at candidate or token budget."""
    outcomes: list[dict] = []
    spent = 0
    for candidate_id in candidate_ids:
        if spent >= token_budget:
            break
        outcome = run_one(candidate_id)
        outcomes.append(outcome)
        spent += max(0, int(outcome.get("generation_tokens", 0)))
        if outcome.get("decision") in {"NO_CANDIDATE", "STOP_BUDGET", "STOP_ERROR"}:
            break
    return outcomes
