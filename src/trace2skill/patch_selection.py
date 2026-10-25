"""Risk-aware evidence filter that preserves SkillOpt's native ranking step."""
from __future__ import annotations

import hashlib
import re

_ABSOLUTE = re.compile(r"\b(always|never|only|all tasks|every task|must use)\b", re.I)
_DISMISSES_INVALID_ACTION_COST = re.compile(
    r"(?:invalid|redundant|unnecessary)\s+(?:actions?|commands?|tool calls?).{0,100}"
    r"(?:no harm|harmless|no cost|free)", re.I | re.S,
)


def filter_patch_pool(patches: list[dict]) -> tuple[list[dict], list[dict]]:
    accepted: list[dict] = []
    rejected: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for wrapper in patches:
        source = str(wrapper.get("source_type", "failure"))
        payload = wrapper.get("patch", wrapper)
        if not isinstance(payload, dict):
            continue
        for edit in payload.get("edits", []):
            if not isinstance(edit, dict):
                continue
            source = str(edit.get("source_type", source))
            reasons = []
            if not edit.get("source_case_ids"):
                reasons.append("missing_train_provenance")
            applicability = str(edit.get("applicability", "")).strip()
            non_applicability = str(edit.get("non_applicability", "")).strip()
            if not applicability or applicability.startswith("REQUIRED:"):
                reasons.append("missing_applicability_precondition")
            if not non_applicability or non_applicability.startswith("REQUIRED:"):
                reasons.append("missing_countercondition")
            if source == "failure" and not edit.get("success_counterexamples"):
                reasons.append("missing_success_counterexample")
            content = str(edit.get("content", "")).strip()
            if re.search(r"\b(?:train|val|test)(?::|__)[0-9]{4}\b", content, re.I):
                reasons.append("benchmark_case_id_in_skill_content")
            if _ABSOLUTE.search(content) and len(non_applicability) < 24:
                reasons.append("unbounded_absolute_rule")
            if _DISMISSES_INVALID_ACTION_COST.search(str(edit.get("regression_risk", ""))):
                reasons.append("invalid_action_cost_dismissed")
            key = (str(edit.get("op")), str(edit.get("target")), content)
            if key in seen:
                reasons.append("duplicate_edit")
            seen.add(key)
            item = {**edit, "source_type": source}
            if not item.get("patch_id"):
                fingerprint = "|".join((
                    source, str(item.get("op", "")), str(item.get("target", "")), content,
                    ",".join(sorted(str(x) for x in (item.get("source_case_ids") or []))),
                ))
                item["patch_id"] = "p-" + hashlib.sha256(fingerprint.encode()).hexdigest()[:12]
            (rejected if reasons else accepted).append({"edit": item, "reasons": reasons})
    return accepted, rejected


def build_native_pool(filtered: list[dict]) -> dict:
    """Convert risk-filter rows or already-unwrapped edits to native input.

    ``filter_patch_pool`` returns ``{"edit": ..., "reasons": ...}`` rows,
    while callers that partition accepted rows by ``source_type`` naturally
    pass the contained edits. Accept both representations so the subsequent
    native SkillOpt selector receives the same edit schema either way.
    """
    return {
        "reasoning": "Risk-aware provenance and applicability checks passed; native SkillOpt ranking follows.",
        "edits": [row.get("edit", row) for row in filtered if isinstance(row, dict)],
    }
