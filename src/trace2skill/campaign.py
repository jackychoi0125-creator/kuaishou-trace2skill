"""Deterministic candidate-loop control, independent of Harbor/model I/O."""
from __future__ import annotations

from collections.abc import Callable


def regressed_success_counterexamples(
    selected_patch: dict, before: dict[str, int], after: dict[str, int],
) -> list[str]:
    """Return cited successful Train cases that a candidate turns into failures.

    The cited cases are a patch's own preservation claim, so a regression on
    them is a stronger warning than a numerically offset aggregate Train score.
    """
    cited = {
        str(case_id)
        for edit in selected_patch.get("edits", [])
        if isinstance(edit, dict)
        for case_id in (edit.get("success_counterexamples") or [])
    }
    return sorted(case_id for case_id in cited if before.get(case_id) == 1 and after.get(case_id) == 0)


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
        spent += max(0, int(outcome.get("new_generation_tokens", outcome.get("generation_tokens", 0))))
        if outcome.get("decision") in {"NO_CANDIDATE", "STOP_BUDGET", "STOP_ERROR"}:
            break
    return outcomes
