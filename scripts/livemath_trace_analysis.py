#!/usr/bin/env python3
"""Offline diagnostics for one official LiveMath Harbor run; never reads keys."""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path


def analyze_trial(trial: Path, *, skill_text: str = "") -> dict:
    result = json.loads((trial / "result.json").read_text(encoding="utf-8"))
    metrics_path = trial / "verifier/metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.is_file() else {}
    submission_path = trial / "agent/submission.json"
    submission = json.loads(submission_path.read_text(encoding="utf-8")) if submission_path.is_file() else {}
    response_path = next(trial.glob("artifacts/bench/answers/*/final-response.txt"), None)
    response = response_path.read_text(encoding="utf-8", errors="replace") if response_path else ""
    trace_path = trial / "agent/trajectory.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8")) if trace_path.is_file() else {}
    steps = trace.get("steps") or []
    calls = [call for step in steps for call in (step.get("tool_calls") or [])]
    loaded_step = None
    for step in steps:
        results = {r.get("source_call_id"): str(r.get("content") or "")
                   for r in ((step.get("observation") or {}).get("results") or [])}
        for call in step.get("tool_calls") or []:
            arguments = call.get("arguments") or {}
            path = str(arguments.get("path") or "")
            command = str(arguments.get("command") or "")
            if (path.endswith("/livemath-strategy/SKILL.md")
                    or "/livemath-strategy/SKILL.md" in command):
                if skill_text and skill_text.rstrip() in results.get(call.get("tool_call_id"), ""):
                    loaded_step = step.get("step_id")
    errors = [str((step.get("extra") or {}).get("error") or "") for step in steps
              if (step.get("extra") or {}).get("stop_reason") == "error"]
    agent = result.get("agent_result") or {}
    reward = ((result.get("verifier_result") or {}).get("rewards") or {}).get("reward")
    boxed = re.findall(r"\\boxed\s*\{\s*([A-Ea-e])\s*\}", response)
    cause = "passed" if reward == 1 else (
        "agent_exception" if result.get("exception_info") else
        "terminal_model_error" if errors else
        "no_response" if not response else
        "unparsed_or_invalid_response" if not isinstance(metrics.get("parsed_answer"), str)
        or metrics["parsed_answer"] not in set("ABCDE") else
        "answer_disagreement_between_boxes" if len(set(x.upper() for x in boxed)) > 1 else
        "scored_wrong_label"
    )
    return {
        "case_id": re.sub(r"^lm(20\d{4})-(\d+)$", r"\1:\2", str(result.get("task_name") or "")),
        "passed": int(reward == 1),
        "cause": cause,
        "answer_status": metrics.get("answer_status"),
        "parsed_answer": metrics.get("parsed_answer"),
        "finish_reason": submission.get("finish_reason"),
        "response_bytes": submission.get("response_bytes"),
        "boxed_label_count": len(boxed),
        "distinct_boxed_labels": len(set(x.upper() for x in boxed)),
        "tool_calls": len(calls),
        "skill_body_loaded_step": loaded_step,
        "atif_steps": len(steps),
        "input_tokens": int(agent.get("n_input_tokens") or 0),
        "output_tokens": int(agent.get("n_output_tokens") or 0),
        "cached_tokens_subset_of_input": int(agent.get("n_cache_tokens") or 0),
        "execution_error": bool(result.get("exception_info")),
        "terminal_model_error": bool(errors),
        "output_limit_reached": submission.get("finish_reason") == "length",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--skill-file", type=Path,
                        help="candidate SKILL.md for verifying the full body in a tool result")
    args = parser.parse_args()
    trials = sorted(f.parent for f in args.job.rglob("result.json")
                    if (f.parent / "agent").is_dir())
    if not trials:
        raise RuntimeError("no official Harbor trial results found")
    skill_text = args.skill_file.read_text(encoding="utf-8") if args.skill_file else ""
    rows = [analyze_trial(trial, skill_text=skill_text) for trial in trials]
    if len({row["case_id"] for row in rows}) != len(rows):
        raise RuntimeError("duplicate official case IDs")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    counts = Counter(row["cause"] for row in rows)
    print(json.dumps({"cases": len(rows), "passed": sum(row["passed"] for row in rows),
                      "causes": counts, "input_tokens": sum(row["input_tokens"] for row in rows),
                      "output_tokens": sum(row["output_tokens"] for row in rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
