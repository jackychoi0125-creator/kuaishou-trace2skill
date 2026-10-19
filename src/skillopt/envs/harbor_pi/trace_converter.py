"""Convert Harbor-exported ATIF v1.8 into SkillOpt reflection conversations."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _family_from_text(text: str) -> str:
    """Coarse, benchmark-agnostic task family labels for contrastive grouping."""
    value = text.casefold()
    patterns = (
        ("formula", r"formula|function|lookup|sumif|cross.sheet|reference"),
        ("structure", r"insert|delete|move|transpose|reorder|row|column|sheet|merge|split"),
        ("value", r"static|value|date|round|extract|copy|fill|replace"),
        ("format", r"format|style|font|color|conditional"),
        ("script", r"script|python|openpyxl|macro"),
    )
    for label, pattern in patterns:
        if re.search(pattern, value):
            return label
    return "general"


def _untrusted(label: str, value: Any) -> str:
    """Mark all trace-sourced text as quoted data, never as instructions."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    label = label.upper()
    return f"[UNTRUSTED {label} TRACE DATA BEGIN]\n{text}\n[UNTRUSTED {label} TRACE DATA END]"


def atif_to_conversation(trace: dict) -> list[dict]:
    if trace.get("schema_version") != "ATIF-v1.8":
        raise ValueError(f"unsupported trace schema: {trace.get('schema_version')!r}")
    conversation: list[dict] = []
    for step in trace.get("steps") or []:
        src = step.get("source")
        role = "assistant" if src == "agent" else "user" if src == "user" else "tool"
        msg = step.get("message")
        if msg:
            conversation.append({"role": role, "content": _untrusted(role, msg)})
        for call in step.get("tool_calls") or []:
            conversation.append(
                {
                    "type": "tool_call",
                    "cmd": _untrusted(
                        "TOOL CALL",
                        {
                            "name": call.get("function_name"),
                            "arguments": call.get("arguments", {}),
                        },
                    ),
                    "obs": "",
                }
            )
        observation = step.get("observation") or {}
        for result in observation.get("results") or []:
            label = "TOOL ERROR RESULT" if (result.get("extra") or {}).get("is_error") else "TOOL RESULT"
            conversation.append({"role": "tool", "content": _untrusted(label, result.get("content", ""))})
        extra = step.get("extra") or {}
        if extra.get("error"):
            conversation.append({"role": "tool", "content": _untrusted("EXECUTION ERROR", extra["error"])})
    return conversation


def convert_record(record: dict, out_dir: str | Path) -> dict:
    trace = record.get("trace") or {}
    task_id = str(record.get("case_id", ""))
    if not task_id:
        raise ValueError("Harbor trace record is missing case_id")
    conversation = atif_to_conversation(trace)
    if not conversation:
        raise ValueError(f"empty ATIF conversation for task {task_id}")
    prediction_dir = Path(out_dir) / "predictions" / task_id
    prediction_dir.mkdir(parents=True, exist_ok=True)
    (prediction_dir / "conversation.json").write_text(
        json.dumps(conversation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    user_text = " ".join(
        str(step.get("message", ""))
        for step in (trace.get("steps") or [])
        if step.get("source") == "user"
    )
    family = _family_from_text(user_text)
    return {
        "id": task_id,
        "hard": int(float(record.get("reward", 0)) >= 1.0),
        "soft": float(record.get("reward", 0)),
        "fail_reason": str(record.get("execution_error") or ""),
        "task_description": f"Task family: {family}",
        "task_type": f"spreadsheet/{family}",
        "n_turns": sum(1 for item in conversation if item.get("role") == "assistant"),
        "trace_path": str(prediction_dir / "conversation.json"),
    }
