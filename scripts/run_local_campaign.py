#!/usr/bin/env python3
"""Run the preflight, 3-task Harbor smoke, and bounded campaign locally.

Credentials are read into this process from the existing private model.txt and
Harbor kit.env files. They are never emitted in argv or this script's output.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
SKILLOPT = HERE.parents[2]
WORKSPACE = HERE.parents[3]
KIT = WORKSPACE / "spreadsheetbench-harbor-kit-v3.3-layout2"
TRACE2SKILL = SKILLOPT / "submission/scripts/trace2skill.py"


def _assignments(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        try:
            parts = shlex.split(value, comments=True)
        except ValueError:
            continue
        result[key.strip()] = parts[0] if parts else ""
    return result


def _model_txt(path: Path) -> tuple[str, dict[str, str]]:
    api_key = ""
    model_ids: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            parts = shlex.split(raw)
        except ValueError:
            continue
        if len(parts) >= 2 and parts[0] == "export" and parts[1].startswith("WQ_API_KEY="):
            api_key = parts[1].split("=", 1)[1]
        elif len(parts) >= 4 and parts[1] == "model_id" and parts[2] == "=":
            model_ids[parts[0]] = parts[3]
        elif len(parts) >= 2 and parts[1].startswith("model_id="):
            model_ids[parts[0]] = parts[1].split("=", 1)[1]
    if not api_key:
        raise RuntimeError("model.txt does not contain the configured WQ_API_KEY")
    return api_key, model_ids


def _smoke_audit(jobs_dir: Path, runner_log: Path) -> dict:
    texts = [runner_log.read_text(encoding="utf-8", errors="replace")]
    trace_files = list(jobs_dir.rglob("traces.jsonl"))
    summaries = []
    for result_path in jobs_dir.rglob("result.json"):
        try:
            result_data = json.loads(result_path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if "n_total_trials" in result_data:
            summaries.append(result_path)
    records = []
    for trace in trace_files:
        for line in trace.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            records.append(record)
    trial_logs = list(jobs_dir.rglob("trial.log")) + list(jobs_dir.rglob("job.log"))
    texts.extend(p.read_text(encoding="utf-8", errors="replace") for p in trial_logs)
    joined = "\n".join(texts)
    rate_limit_count = len(re.findall(r"(?i)\b429\b|too many requests|rate.?limit|retry-after", joined))
    provider_error_count = len(re.findall(r"(?i)APIStatusError|APIConnectionError|RateLimitError|\bHTTP 5\d\d\b", joined))
    tool_errors = 0
    for record in records:
        trace = record.get("trace") or {}
        for step in trace.get("steps") or []:
            tool_errors += int(bool((step.get("extra") or {}).get("error")))
            observation = step.get("observation") or {}
            tool_errors += sum(bool((x.get("extra") or {}).get("is_error")) for x in observation.get("results") or [])
    task_errors = 0
    completed_trials = errored_trials = retries = 0
    input_tokens = cache_tokens = output_tokens = 0
    for summary in summaries:
        try:
            data = json.loads(summary.read_text(encoding="utf-8"))
        except ValueError:
            continue
        stats = data.get("stats") or {}
        completed_trials += int(stats.get("n_completed_trials", 0) or 0)
        errored_trials += int(stats.get("n_errored_trials", 0) or 0)
        retries += int(stats.get("n_retries", 0) or 0)
        input_tokens += int(stats.get("n_input_tokens", 0) or 0)
        cache_tokens += int(stats.get("n_cache_tokens", 0) or 0)
        output_tokens += int(stats.get("n_output_tokens", 0) or 0)
        for key in ("errored", "errors", "failed", "exceptions"):
            value = data.get(key)
            if isinstance(value, int):
                task_errors += value
    truncation_count = 0
    for session in jobs_dir.rglob("agent/pi/sessions/*.jsonl"):
        for line in session.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            message = event.get("message") or {}
            usage = message.get("usage") or {}
            reason = str(message.get("stopReason") or message.get("rawStopReason") or "").lower()
            if reason in {"length", "max_tokens", "max_completion_tokens"}:
                truncation_count += 1
            if int(usage.get("output", 0) or 0) >= 65536:
                truncation_count += 1
    return {
        "expected_tasks": 3,
        "trace_records": len(records),
        "summary_files": len(summaries),
        "completed_trials": completed_trials,
        "errored_trials": errored_trials,
        "retries": retries,
        "rate_limit_markers_429": rate_limit_count,
        "provider_error_markers": provider_error_count,
        "tool_error_events": tool_errors,
        "truncation_markers": truncation_count,
        "task_error_count_from_summary": task_errors,
        "target_input_tokens": input_tokens,
        "target_cache_tokens_subset": cache_tokens,
        "target_output_tokens": output_tokens,
        "target_total_tokens": input_tokens + output_tokens,
        "runner_log": str(runner_log),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--max-candidates", type=int, default=2)
    parser.add_argument("--token-budget", type=int, default=900000)
    args = parser.parse_args()

    run_root = Path(args.run_root).resolve()
    if run_root.exists() and any(run_root.iterdir()) and not (
        (run_root / "model_config_report.json").is_file() and (run_root / "smoke").is_dir()
    ):
        raise FileExistsError(f"run directory is not empty: {run_root}")
    run_root.mkdir(parents=True, exist_ok=True)

    kit_settings = _assignments(KIT / "kit.env")
    api_key, model_ids = _model_txt(WORKSPACE / "model.txt")
    base_url = kit_settings.get("KIT_BASE_URL", "").strip().strip("'\"")
    if not base_url.startswith("https://"):
        raise RuntimeError("kit.env KIT_BASE_URL must be HTTPS")

    # Verify public model IDs against the active Round 1 config before any call.
    import yaml

    public = yaml.safe_load((SKILLOPT / "configs/harbor_pi/default.yaml").read_text(encoding="utf-8"))["model"]
    expected = {
        "kimi-k2.6": str(public["optimizer_openai_compatible_model"]),
        "deepseek-v4-flash": str(public["target_openai_compatible_model"]),
    }
    if any(model_ids.get(name) != value for name, value in expected.items()):
        raise RuntimeError("model.txt model IDs do not match the active Round 1 config")

    os.environ.update(
        {
            "TRACE2SKILL_DIRECT_LOCAL": "1",
            "TRACE2SKILL_LOCAL_BASE_URL": base_url,
            "TRACE2SKILL_TARGET_BASE_URL": base_url,
            "TRACE2SKILL_OPTIMIZER_BASE_URL": base_url,
            "TRACE2SKILL_TARGET_API_KEY": api_key,
            "TRACE2SKILL_OPTIMIZER_API_KEY": api_key,
        }
    )
    env = os.environ.copy()

    # Live probes verify target tool calls/thinking-off and Kimi thinking-on/90K.
    sys.path.insert(0, str(SKILLOPT))
    from submission.scripts.trace2skill import model_check  # noqa: PLC0415

    model_report_path = run_root / "model_config_report.json"
    if model_report_path.is_file():
        model_report = json.loads(model_report_path.read_text(encoding="utf-8"))
        target_report = model_report.get("target") or {}
        optimizer_report = model_report.get("optimizer") or {}
        backend_probe = optimizer_report.get("skillopt_backend_probe") or {}
        if not (
            target_report.get("http_status") == 200
            and target_report.get("thinking") == "off"
            and target_report.get("tool_calls", 0) > 0
            and target_report.get("reasoning_tokens", -1) == 0
            and optimizer_report.get("http_status") == 200
            and optimizer_report.get("thinking") == "on"
            and optimizer_report.get("max_completion_tokens_accepted") is True
            and (optimizer_report.get("max_completion_tokens_enforced") or {}).get("actual_completion_tokens") == 1
            and backend_probe.get("wire_max_completion_tokens") == 90000
            and backend_probe.get("reasoning_content_present") is True
        ):
            raise RuntimeError("saved model probe report does not satisfy the configured model checks")
        print("reusing successful model probes from this run directory")
    else:
        model_report = model_check(model_report_path)
        print("model probes passed; starting concurrent=1 Harbor smoke")

    smoke_jobs = run_root / "smoke"
    smoke_log = run_root / "smoke.log"
    if smoke_jobs.exists():
        audit = _smoke_audit(smoke_jobs, smoke_log)
        audit["exit_code"] = 0 if audit["completed_trials"] == 3 else 1
        print("reusing completed Harbor smoke and recomputing its offline audit")
    else:
        command = [
            str(KIT / "run.sh"), "--bench", "spreadsheetbench-train",
            "--model-id", expected["deepseek-v4-flash"], "--base-url", base_url,
            "--reasoning", "off", "--concurrent", "1", "--n", "3",
            "--jobs-dir", str(smoke_jobs),
        ]
        with smoke_log.open("w", encoding="utf-8") as log:
            completed = subprocess.run(command, cwd=WORKSPACE, env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
        audit = _smoke_audit(smoke_jobs, smoke_log) if smoke_jobs.exists() else {
            "expected_tasks": 3, "trace_records": 0, "summary_files": 0,
            "completed_trials": 0, "errored_trials": 1, "retries": 0,
            "rate_limit_markers_429": 0, "provider_error_markers": 0,
            "tool_error_events": 0, "truncation_markers": 0,
            "task_error_count_from_summary": 0, "runner_log": str(smoke_log),
        }
        audit["exit_code"] = completed.returncode
    (run_root / "smoke_audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    if (
        audit["exit_code"] or audit["trace_records"] != 3 or audit["completed_trials"] != 3
        or audit["errored_trials"] or audit["retries"] or audit["rate_limit_markers_429"]
        or audit["provider_error_markers"] or audit["truncation_markers"]
    ):
        print(f"smoke did not qualify for training; see {run_root / 'smoke_audit.json'}")
        raise SystemExit(2)

    train_trace = WORKSPACE / "spreadsheetbench-harbor-kit-v3.3-layout2/workspace/traces/train-baseline-nothink.jsonl"
    if not train_trace.is_file():
        raise FileNotFoundError("saved DeepSeek Thinking OFF Train baseline Trace is missing")
    campaign_command = [
        sys.executable, str(TRACE2SKILL), "search",
        "--run-root", str(run_root / "campaign"),
        "--initial-train-trace", str(train_trace),
        "--max-candidates", str(args.max_candidates),
        "--token-budget", str(args.token_budget),
        "--resume",
    ]
    with (run_root / "campaign.log").open("w", encoding="utf-8") as log:
        campaign = subprocess.run(campaign_command, cwd=WORKSPACE, env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
    (run_root / "execution_status.json").write_text(
        json.dumps(
            {
                "status": "CAMPAIGN_FINISHED" if campaign.returncode == 0 else "CAMPAIGN_FAILED",
                "model_probes": {
                    "target_thinking": model_report["target"]["thinking"],
                    "target_finish_reason": model_report["target"]["finish_reason"],
                    "optimizer_thinking": model_report["optimizer"]["thinking"],
                    "optimizer_finish_reason": model_report["optimizer"]["finish_reason"],
                    "optimizer_max_completion_tokens": 90000,
                    "optimizer_max_completion_tokens_accepted": model_report["optimizer"].get(
                        "max_completion_tokens_accepted"
                    ),
                    "optimizer_max_completion_tokens_enforced": model_report["optimizer"].get(
                        "max_completion_tokens_enforced"
                    ),
                },
                "smoke": audit,
                "campaign_exit_code": campaign.returncode,
                "campaign_log": str(run_root / "campaign.log"),
                "credentials_logged": False,
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(f"campaign_exit_code={campaign.returncode}; artifacts={run_root}")
    if campaign.returncode:
        raise SystemExit(campaign.returncode)


if __name__ == "__main__":
    main()
