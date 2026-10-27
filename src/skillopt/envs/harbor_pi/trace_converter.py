"""Convert Harbor-exported ATIF v1.8 into SkillOpt reflection conversations."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def normalize_case_id(case_id: Any) -> str:
    """Map Harbor's filesystem-safe task name to the official split ID."""
    value = str(case_id or "")
    match = re.fullmatch(r"(train|val|test)__(\d{4})", value)
    if match:
        return f"{match.group(1)}:{match.group(2)}"
    livemath = re.fullmatch(r"lm(20\d{4})-(\d+)", value)
    if livemath:
        return f"{livemath.group(1)}:{livemath.group(2)}"
    return value


def terminal_model_error(trace: dict) -> str:
    """Return the final Pi model error, ignoring recovered earlier errors."""
    agents = [step for step in (trace.get("steps") or []) if step.get("source") == "agent"]
    if not agents:
        return ""
    extra = agents[-1].get("extra") or {}
    return str(extra.get("error") or "model_error") if extra.get("stop_reason") == "error" else ""


def _family_from_text(text: str, task_type: str = "") -> str:
    """Coarse, benchmark-agnostic task family labels for contrastive grouping."""
    value = text.casefold()
    declared = str(task_type or "").casefold().strip()
    alf_families = (
        "pick_two_obj_and_place", "pick_clean_then_place_in_recep",
        "pick_heat_then_place_in_recep", "pick_cool_then_place_in_recep",
        "look_at_obj_in_light", "pick_and_place_simple",
    )
    for family in alf_families:
        if family in declared or family in value:
            return family
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


def _livemath_family(text: str) -> str:
    """Coarse public-question domains; labels never use scores or answer keys."""
    patterns = (
        ("algebra_geometry", r"\b(scheme|sheaf|variety|cohomology|ideal|module|algebraic)\b"),
        ("analysis_pde", r"\b(PDE|Sobolev|elliptic|Schr[oö]dinger|Navier|Laplace|fluid)\b|\\Delta"),
        ("probability", r"\b(probability|random|stochastic|martingale|Gaussian)\b"),
        ("discrete_math", r"\b(graph|combinator|integer|finite group|lattice|partition|matrix)\b"),
    )
    for name, pattern in patterns:
        if re.search(pattern, text, re.I):
            return name
    return "general_math"


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


def convert_record(record: dict, out_dir: str | Path, *, task_type: str = "", benchmark: str = "spreadsheetbench") -> dict:
    trace = record.get("trace") or {}
    task_id = normalize_case_id(record.get("case_id", ""))
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
    family = _livemath_family(user_text) if benchmark == "livemath" else _family_from_text(user_text, task_type)
    model_unavailable = (
        int(record.get("input_tokens") or 0) == 0
        and int(record.get("output_tokens") or 0) == 0
        and not any(step.get("tool_calls") for step in (trace.get("steps") or []))
    )
    terminal_error = terminal_model_error(trace)
    return {
        "id": task_id,
        "hard": int(float(record.get("reward", 0)) >= 1.0),
        "soft": float(record.get("reward", 0)),
        "execution_error": bool(record.get("execution_error")),
        "model_unavailable": model_unavailable,
        "terminal_model_error": bool(terminal_error),
        "fail_reason": terminal_error or ("model_unavailable" if model_unavailable else str(record.get("execution_error") or "")),
        "task_description": f"Benchmark: {benchmark}; task family: {family}",
        "task_type": f"{benchmark}/{task_type or family}",
        "n_turns": sum(1 for item in conversation if item.get("role") == "assistant"),
        "trace_path": str(prediction_dir / "conversation.json"),
    }
