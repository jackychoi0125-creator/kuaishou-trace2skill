#!/usr/bin/env python3
"""Trace2Skill Harbor + SkillOpt command line, with auditable checkpoints."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _find_workspace() -> Path:
    configured = os.environ.get("TRACE2SKILL_WORKSPACE")
    if configured:
        return Path(configured).expanduser().resolve()
    for parent in (ROOT, *ROOT.parents):
        if (parent / "spreadsheetbench-harbor-kit-v3.3-layout2").is_dir():
            return parent
    return ROOT.parent


WORKSPACE = _find_workspace()
KIT = Path(os.environ.get("HARBOR_KIT_ROOT", WORKSPACE / "spreadsheetbench-harbor-kit-v3.3-layout2")).expanduser().resolve()


def benchmark_name() -> str:
    manifest = KIT / "benchmark/splits/split_manifest.json"
    if manifest.is_file():
        value = str(json.loads(manifest.read_text(encoding="utf-8")).get("benchmark", "")).casefold()
        if value == "alfworld":
            return "alfworld"
    return "spreadsheetbench"


def _skillopt_revision() -> str:
    provenance = ROOT / "UPSTREAM_SKILLOPT.md"
    if provenance.is_file():
        for line in provenance.read_text(encoding="utf-8").splitlines():
            if line.startswith("Vendored project snapshot:"):
                return line.partition(":")[2].strip()
    try:
        return subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown-vendored-revision"

from skillopt.envs.harbor_pi.rollout import HarborKitRollout  # noqa: E402
from skillopt.envs.harbor_pi.security import assert_real_run_ready, proxy_credentials  # noqa: E402
from skillopt.envs.harbor_pi.skill_packager import package_skill  # noqa: E402
from skillopt.envs.harbor_pi.trace_converter import convert_record, normalize_case_id, terminal_model_error  # noqa: E402


def read_models() -> dict[str, str]:
    """Read model IDs from the public YAML; never parse private model.txt."""
    import yaml

    model_cfg = yaml.safe_load((ROOT / "configs/harbor_pi/default.yaml").read_text(encoding="utf-8"))["model"]
    return {
        "kimi-k2.6": str(model_cfg["optimizer_openai_compatible_model"]),
        "deepseek-v4-flash": str(model_cfg["target_openai_compatible_model"]),
    }


def model_check(out_path: Path) -> dict:
    """Live probes for DS non-thinking tool calls and Kimi thinking + 90k cap."""
    import urllib.request

    assert_real_run_ready()
    models = read_models()
    target_proxy = proxy_credentials("target")
    optimizer_proxy = proxy_credentials("optimizer")
    url = target_proxy.base_url.rstrip("/") + "/chat/completions"

    def request(model: str, body: dict) -> dict:
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {target_proxy.token if model == models['deepseek-v4-flash'] else optimizer_proxy.token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.loads(response.read())
            result["_http_status"] = response.status
            return result

    ds_body = {
        "model": models["deepseek-v4-flash"],
        "messages": [{"role": "user", "content": "Call probe once with value 7."}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "probe",
                    "description": "probe",
                    "parameters": {
                        "type": "object",
                        "properties": {"value": {"type": "integer"}},
                        "required": ["value"],
                    },
                },
            }
        ],
        "tool_choice": "auto",
        "max_tokens": 96,
        "stream": False,
        "reasoning_effort": "none",
        "thinking": {"type": "disabled"},
    }
    ds = request(models["deepseek-v4-flash"], ds_body)
    ds_choice = (ds.get("choices") or [{}])[0]
    ds_message = ds_choice.get("message") or {}
    ds_usage = ds.get("usage") or {}
    if ds_choice.get("finish_reason") != "tool_calls" or not ds_message.get("tool_calls"):
        raise RuntimeError("DeepSeek non-thinking probe did not complete its tool call")
    if int(ds_usage.get("reasoning_tokens", 0) or 0) != 0 or ds_message.get("reasoning_content"):
        raise RuntimeError("DeepSeek non-thinking probe returned reasoning tokens/content")

    kimi_body = {
        "model": models["kimi-k2.6"],
        "messages": [{"role": "user", "content": "Think briefly and answer 2+2."}],
        "max_completion_tokens": 90000,
        "stream": False,
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }
    url = optimizer_proxy.base_url.rstrip("/") + "/chat/completions"
    kimi = request(models["kimi-k2.6"], kimi_body)
    kimi_choice = (kimi.get("choices") or [{}])[0]
    kimi_message = kimi_choice.get("message") or {}
    kimi_usage = kimi.get("usage") or {}
    kimi_details = kimi_usage.get("completion_tokens_details") or {}
    reasoning = int(kimi_details.get("reasoning_tokens", kimi_usage.get("reasoning_tokens", 0)) or 0)
    if kimi_choice.get("finish_reason") not in {"stop", "tool_calls"} or not kimi_message.get("reasoning_content"):
        raise RuntimeError("Kimi Thinking ON probe returned no reasoning_content")
    cap_body = {
        "model": models["kimi-k2.6"],
        "messages": [{"role": "user", "content": "Write a detailed explanation of a validation workflow."}],
        "max_completion_tokens": 1,
        "stream": False,
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }
    cap_observations = []
    for _ in range(3):
        cap_probe = request(models["kimi-k2.6"], cap_body)
        cap_choice = (cap_probe.get("choices") or [{}])[0]
        cap_usage = cap_probe.get("usage") or {}
        cap_completion = int(cap_usage.get("completion_tokens", 0) or 0)
        cap_observations.append({"finish_reason": cap_choice.get("finish_reason"), "completion_tokens": cap_completion})
        if cap_choice.get("finish_reason") == "length" and cap_completion == 1:
            break
    if cap_choice.get("finish_reason") != "length" or cap_completion != 1:
        raise RuntimeError(
            "Kimi max_completion_tokens control differed: "
            f"observations={cap_observations!r}"
        )
    from skillopt.model.openai_compatible_backend import chat_optimizer, configure_openai_compatible

    configure_openai_compatible(
        optimizer_base_url=optimizer_proxy.base_url,
        optimizer_api_key=optimizer_proxy.token,
        optimizer_model=models["kimi-k2.6"],
        optimizer_max_tokens=90000,
        optimizer_completion_token_field="max_completion_tokens",
        optimizer_thinking="enabled",
        optimizer_reasoning_effort="high",
        optimizer_timeout_seconds=120,
        optimizer_temperature=0.2,
    )
    sdk_text, sdk_usage = chat_optimizer(
        system="You are a concise configuration probe.",
        user="Think briefly and answer 2+2.",
        max_completion_tokens=16384,
        retries=1,
        stage="model_config_probe",
    )
    if not sdk_text.strip() or not sdk_usage.get("reasoning_content_present"):
        raise RuntimeError("SkillOpt OpenAI-compatible Kimi backend did not preserve Thinking output")

    report = {
        "verified_at_local": time.strftime("%Y-%m-%d %H:%M:%S%z"),
        "endpoint": url.rsplit("/chat/completions", 1)[0],
        "target": {
            "role": "Harbor Pi Agent",
            "model_id": models["deepseek-v4-flash"],
            "http_status": ds.get("_http_status"),
            "thinking": "off",
            "request_parameters": {"thinking": {"type": "disabled"}, "reasoning_effort": "none"},
            "response_model": ds.get("model"),
            "finish_reason": ds_choice.get("finish_reason"),
            "tool_calls": len(ds_message.get("tool_calls") or []),
            "reasoning_tokens": int(ds_usage.get("reasoning_tokens", 0) or 0),
            "reasoning_content_present": bool(ds_message.get("reasoning_content")),
            "prompt_tokens": int(ds_usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(ds_usage.get("completion_tokens", 0) or 0),
        },
        "optimizer": {
            "role": "SkillOpt optimizer",
            "model_id": models["kimi-k2.6"],
            "http_status": kimi.get("_http_status"),
            "thinking": "on",
            "request_parameters": {
                "thinking": {"type": "enabled"},
                "reasoning_effort": "high",
                "max_completion_tokens": 90000,
            },
            "response_model": kimi.get("model"),
            "finish_reason": kimi_choice.get("finish_reason"),
            "reasoning_tokens": reasoning,
            "reasoning_content_present": bool(kimi_message.get("reasoning_content")),
            "prompt_tokens": int(kimi_usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(kimi_usage.get("completion_tokens", 0) or 0),
            "max_completion_tokens_accepted": True,
            "max_completion_tokens_enforced": {
                "test_cap": 1,
                "finish_reason": cap_choice.get("finish_reason"),
                "actual_completion_tokens": cap_completion,
                "probe_observations": cap_observations,
            },
            "skillopt_backend_probe": {
                "http_status": 200,
                "wire_completion_token_field": "max_completion_tokens",
                "wire_max_completion_tokens": 90000,
                "wire_thinking": {"type": "enabled"},
                "wire_reasoning_effort": "high",
                "wire_temperature": 0.2,
                "finish_reason": sdk_usage.get("finish_reason"),
                "reasoning_content_present": sdk_usage.get("reasoning_content_present"),
                "usage": {
                    k: sdk_usage.get(k, 0)
                    for k in ("prompt_tokens", "completion_tokens", "reasoning_tokens", "cached_tokens", "total_tokens")
                },
            },
        },
        "credentials_persisted": False,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _trace_file(split: str, path: str | None = None) -> Path:
    if path:
        return Path(path).resolve()
    base = KIT / "workspace/runs" / f"{benchmark_name()}-{split}-baseline-nothink"
    runs = sorted(base.glob("*/traces.jsonl"))
    if len(runs) != 1:
        raise FileNotFoundError(f"expected exactly one {split} traces.jsonl under {base}; found {len(runs)}")
    return runs[0]


def load_records(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(path)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for record in records:
        record["case_id"] = normalize_case_id(record.get("case_id"))
    return records


def _harbor_error_counts(job_dir: Path, trace_path: Path, summary: dict) -> dict:
    model_events = model_trials = exception_trials = 0
    for trial in job_dir.iterdir():
        result_path = trial / "result.json"
        if not result_path.is_file():
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        verifier = result.get("verifier_result") or {}
        missing_reward = (verifier.get("rewards") or {}).get("reward") is None
        if result.get("exception_info") or missing_reward:
            exception_trials += 1
        pi_log = trial / "agent/pi.txt"
        this_trial = 0
        if pi_log.is_file():
            for line in pi_log.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                message = event.get("message") or {}
                if isinstance(message, dict) and message.get("stopReason") == "error":
                    this_trial += 1
        model_events += this_trial
        model_trials += int(this_trial > 0)
    trace_records = load_records(trace_path)
    return {
        "model_error_events": model_events,
        "model_error_trials": model_trials,
        "task_exception_trials": exception_trials,
        "business_failed_trials": int(summary.get("failed", 0)),
        "harbor_error_trials": int(summary.get("errors", 0)),
        "trace_execution_error_trials": sum(bool(x.get("execution_error")) for x in trace_records),
    }


def convert_trace_file(trace_file: Path, split: str, out_dir: Path) -> list[dict]:
    expected = json.loads((KIT / f"benchmark/splits/{split}/items.json").read_text(encoding="utf-8"))
    task_types = {str(row["id"]): str(row.get("task_type", "")) for row in expected}
    expected_ids = {str(row["id"]) for row in expected}
    records = load_records(trace_file)
    actual_ids = {str(row.get("case_id")) for row in records}
    if len(records) != len(expected_ids) or actual_ids != expected_ids:
        raise ValueError(f"{split} trace IDs do not exactly match the official split")
    (out_dir / "predictions").mkdir(parents=True, exist_ok=True)
    results = [
        convert_record(
            row, out_dir,
            task_type=task_types.get(str(row.get("case_id", "")), ""),
            benchmark=benchmark_name(),
        )
        for row in records
    ]
    (out_dir / "rollouts.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "split": split,
        "trace_file": str(trace_file),
        "sample_count": len(records),
        "ids_sha256": hashlib.sha256("\n".join(sorted(expected_ids)).encode()).hexdigest(),
        "score_source": "Harbor exported result.reward",
    }
    (out_dir / "conversion_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return results


def configure_optimizer() -> dict:
    from skillopt.model import set_optimizer_backend, set_target_backend
    from skillopt.model.openai_compatible_backend import (
        configure_openai_compatible,
        reset_token_tracker,
        set_optimizer_token_budget,
    )

    assert_real_run_ready()
    models = read_models()
    optimizer_proxy = proxy_credentials("optimizer")
    target_proxy = proxy_credentials("target")
    # SkillOpt defaults optimizer chat to Azure OpenAI. Pin both role
    # dispatchers explicitly; the target remains descriptive here and task
    # execution still goes through HarborPiAdapter.
    set_optimizer_backend("openai_compatible")
    set_target_backend("openai_compatible")
    configure_openai_compatible(
        optimizer_base_url=optimizer_proxy.base_url,
        optimizer_api_key=optimizer_proxy.token,
        optimizer_model=models["kimi-k2.6"],
        optimizer_max_tokens=90000,
        optimizer_completion_token_field="max_completion_tokens",
        optimizer_thinking="enabled",
        optimizer_reasoning_effort="high",
        optimizer_timeout_seconds=600,
        optimizer_temperature=0.2,
        # Target is configured only as descriptive metadata. Actual target tasks
        # are invoked by Harbor Kit and never use SkillOpt's chat_target().
        target_base_url=target_proxy.base_url,
        target_api_key=target_proxy.token,
        target_model=models["deepseek-v4-flash"],
        target_max_tokens=65536,
        target_completion_token_field="max_tokens",
        target_thinking="disabled",
        target_reasoning_effort="none",
    )
    reset_token_tracker()
    set_optimizer_token_budget(int(__import__("os").environ.get("TRACE2SKILL_GENERATION_TOKEN_BUDGET", "900000")))
    return models


def evolve(args: argparse.Namespace) -> dict:
    from trace2skill.contrastive_reflect import run_contrastive_reflect
    from trace2skill.patch_selection import build_native_pool, filter_patch_pool

    from skillopt.gradient.aggregate import merge_patches
    from skillopt.model.openai_compatible_backend import get_token_summary
    from skillopt.optimizer.clip import rank_and_select
    from skillopt.optimizer.skill import apply_patch_with_report
    from skillopt.optimizer.update_modes import get_payload_items

    run_dir = Path(args.run_dir).resolve()
    if run_dir.exists() and not args.resume:
        raise FileExistsError(f"run directory already exists; pass --resume to continue: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    conversion = run_dir / "converted-train"
    trace_file = Path(args.train_trace).resolve() if args.train_trace else _trace_file("train")
    if not (conversion / "rollouts.json").is_file():
        results = convert_trace_file(trace_file, "train", conversion)
    else:
        results = json.loads((conversion / "rollouts.json").read_text(encoding="utf-8"))

    config = json.loads((run_dir / "run_config.json").read_text()) if (run_dir / "run_config.json").exists() else None
    if config and config.get("stage") in {"candidate_created", "evaluated", "decided", "no_candidate"}:
        print(f"resuming from stage={config['stage']}")
        return config
    models = configure_optimizer()
    initial_path = Path(args.initial_skill).resolve() if args.initial_skill else None
    if initial_path is None:
        best_path = run_dir.parent / "best/best_skill.md"
        initial_path = best_path if best_path.is_file() else ROOT / "src/skillopt/envs/harbor_pi/skills/initial.md"
    initial = initial_path.read_text(encoding="utf-8")
    candidate_id = run_dir.name
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}", candidate_id):
        raise ValueError(f"unsafe candidate run id: {candidate_id!r}")
    rejected_contexts = []
    for prior in sorted(run_dir.parent.glob("*/rejected_edit_buffer.json")):
        prior_config = prior.parent / "run_config.json"
        if not prior_config.is_file():
            continue
        prior_audit = json.loads(prior_config.read_text(encoding="utf-8"))
        if prior_audit.get("benchmark") == benchmark_name():
            rejected_contexts.append({"source": str(prior), **json.loads(prior.read_text(encoding="utf-8"))})
    rejected_context = json.dumps(rejected_contexts, ensure_ascii=False, indent=2) if rejected_contexts else ""
    reflect_dir = run_dir / "reflect"
    if (reflect_dir / "raw-patches.json").is_file():
        patches = json.loads((reflect_dir / "raw-patches.json").read_text(encoding="utf-8"))
    else:
        patches = run_contrastive_reflect(
            results=results,
            prediction_dir=conversion / "predictions",
            patches_dir=reflect_dir / "patches",
            skill_content=initial,
            batch_size=int(args.minibatch_size),
            edit_budget=int(args.edit_budget),
            step_buffer_context=rejected_context,
            workers=1,
            benchmark=benchmark_name(),
        )
        (reflect_dir / "raw-patches.json").write_text(json.dumps(patches, ensure_ascii=False, indent=2) + "\n")

    eligible, rejected_edits = filter_patch_pool(patches)
    failure_edits = [x["edit"] for x in eligible if x["edit"].get("source_type") == "failure"]
    success_edits = [x["edit"] for x in eligible if x["edit"].get("source_type") == "success"]
    risk_report = {
        "eligible_count": len(eligible),
        "rejected": [{"patch_id": x["edit"].get("patch_id"), "reasons": x["reasons"]} for x in rejected_edits],
        "selection_policy": "one edit per candidate; preserve provenance and preconditions",
    }
    (run_dir / "select").mkdir(parents=True, exist_ok=True)
    (run_dir / "select/risk-filter.json").write_text(json.dumps(risk_report, indent=2) + "\n")
    if (run_dir / "aggregate/merged-patch.json").is_file():
        merged = json.loads((run_dir / "aggregate/merged-patch.json").read_text())
    else:
        failure = [build_native_pool(failure_edits)] if failure_edits else []
        success = [build_native_pool(success_edits)] if success_edits else []
        merged = merge_patches(initial, failure, success, batch_size=8, verbose=True, workers=1, update_mode="patch")
        (run_dir / "aggregate").mkdir(parents=True, exist_ok=True)
        (run_dir / "aggregate/merged-patch.json").write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n")
    selected_path = run_dir / "select/selected-patch.json"
    if selected_path.is_file():
        selected = json.loads(selected_path.read_text())
    else:
        merged_eligible, merged_rejected = filter_patch_pool([merged])
        if not merged_eligible:
            selected = {"reasoning": "all edits rejected by evidence/risk filter", "edits": []}
            risk_report["post_aggregate_rejected"] = [
                {"patch_id": x["edit"].get("patch_id"), "reasons": x["reasons"]} for x in merged_rejected
            ]
            (run_dir / "select/risk-filter.json").write_text(json.dumps(risk_report, indent=2) + "\n")
        else:
            rank_input = {**merged, "edits": [x["edit"] for x in merged_eligible]}
            selected = rank_and_select(
                initial, rank_input, max_edits=min(1, int(args.edit_budget)),
                update_mode="patch", rejected_context=rejected_context,
            )
        selected_path.parent.mkdir(parents=True, exist_ok=True)
        selected_path.write_text(json.dumps(selected, ensure_ascii=False, indent=2) + "\n")
    candidate_text, reports = apply_patch_with_report(initial, selected)
    seed_placeholder = (
        "No benchmark-derived strategies have been learned yet. "
        "Use the agent's normal reasoning and the environment feedback."
    )
    removed_seed_placeholder = bool(
        get_payload_items(selected, "patch") and seed_placeholder in candidate_text
    )
    if removed_seed_placeholder:
        # The no-skill optimizer seed is metadata for generation, not advice
        # to put beside a newly learned strategy in the Pi-visible candidate.
        candidate_text = candidate_text.replace(seed_placeholder + "\n\n", "")
        candidate_text = candidate_text.replace(seed_placeholder, "")
    candidate_file = run_dir / "candidate/skill.md"
    candidate_file.parent.mkdir(parents=True, exist_ok=True)
    candidate_file.write_text(candidate_text, encoding="utf-8")
    skill_file = package_skill(candidate_text, run_dir / "candidate/skills")
    if skill_file.read_text(encoding="utf-8") != candidate_text.rstrip() + "\n":
        raise AssertionError("packaged Pi skill does not match SkillOpt candidate")
    optimizer_usage = get_token_summary()
    optimizer_totals = optimizer_usage.get("_total", {})
    audit = {
        "stage": "candidate_created" if get_payload_items(selected, "patch") else "no_candidate",
        "candidate_id": candidate_id,
        "benchmark": benchmark_name(),
        "seed": 42,
        "skillopt_revision": _skillopt_revision(),
        "target_model_id": models["deepseek-v4-flash"],
        "target_thinking": "off",
        "optimizer_model_id": models["kimi-k2.6"],
        "optimizer_thinking": "on",
        "optimizer_max_completion_tokens": 90000,
        "trace_file": str(trace_file),
        "failure_only": False,
        "reflection_mode": "success_failure_contrastive",
        "train_samples": len(results),
        "failed_train_samples": sum(not r["hard"] for r in results),
        "reflect_eligible_failed_samples": sum(
            not r["hard"] and not r.get("execution_error") and not r.get("model_unavailable") and not r.get("terminal_model_error")
            for r in results
        ),
        "excluded_execution_error_samples": sum(bool(r.get("execution_error")) for r in results),
        "excluded_model_unavailable_samples": sum(bool(r.get("model_unavailable")) for r in results),
        "excluded_terminal_model_error_samples": sum(bool(r.get("terminal_model_error")) for r in results),
        "rejected_buffer_sources": [x["source"] for x in rejected_contexts],
        "reflect_batches": len([p for p in patches if p]),
        "aggregate_patch_count": len(get_payload_items(merged, "patch")),
        "selected_patch_count": len(get_payload_items(selected, "patch")),
        "apply_report": reports,
        "removed_seed_placeholder": removed_seed_placeholder,
        "skill_path": str(skill_file),
        "skill_sha256": hashlib.sha256(candidate_text.encode()).hexdigest(),
        "skill_chars": len(candidate_text),
        "optimizer_token_usage": optimizer_usage,
        "total_skill_generation_tokens": int(optimizer_totals.get("total_tokens", 0)),
    }
    (run_dir / "run_config.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    return audit


def _initial_skill_path() -> Path:
    configured = os.environ.get("TRACE2SKILL_INITIAL_SKILL", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if benchmark_name() == "alfworld":
        return ROOT / "src/skillopt/envs/alfworld/skills/blank.md"
    return ROOT / "src/skillopt/envs/harbor_pi/skills/initial.md"


def _seed_best_from_initial(best_root: Path, val_accuracy: float) -> None:
    best_skill = best_root / "best_skill.md"
    if best_skill.is_file():
        return
    initial_skill = _initial_skill_path()
    initial_text = initial_skill.read_text(encoding="utf-8")
    best_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(initial_skill, best_skill)
    skill_enabled = os.environ.get("TRACE2SKILL_INITIAL_NO_SKILL", "0") != "1"
    if skill_enabled:
        package_skill(initial_text, best_root / "skills")
    (best_root / "best.json").write_text(
        json.dumps(
            {
                "candidate_id": "R0",
                "val_accuracy": val_accuracy,
                "skill_sha256": hashlib.sha256(initial_text.encode()).hexdigest(),
                "skill_enabled": skill_enabled,
                "source": "initial Skill; rejected candidate left Best unchanged",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def evaluate_candidate(args: argparse.Namespace) -> dict:
    from skillopt.evaluation.gate import evaluate_gate

    run_dir = Path(args.run_dir).resolve()
    decision_file = run_dir / "decision.json"
    if decision_file.is_file():
        decision = json.loads(decision_file.read_text(encoding="utf-8"))
        if not decision.get("accept"):
            _seed_best_from_initial(run_dir.parent / "best", float(decision["baseline_val_accuracy"]))
        return decision
    audit_path = run_dir / "run_config.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if audit.get("stage") not in {"candidate_created", "evaluated", "decided"}:
        raise ValueError("candidate must be generated before evaluation")
    val_trace = Path(args.val_trace).resolve() if args.val_trace else _trace_file("val")
    baseline_records = load_records(val_trace)
    baseline = {str(r["case_id"]): int(float(r.get("reward", 0)) >= 1.0) for r in baseline_records}
    best_state_path = run_dir.parent / "best/best.json"
    best_state = json.loads(best_state_path.read_text()) if best_state_path.is_file() else {}
    if best_state.get("val_by_id"):
        baseline = {str(k): int(v) for k, v in best_state["val_by_id"].items()}
    expected = {str(r["id"]) for r in json.loads((KIT / "benchmark/splits/val/items.json").read_text())}
    if set(baseline) != expected:
        raise ValueError("Val baseline trace does not match the official full Val split")
    candidate_rollout = HarborKitRollout(KIT, run_dir / "harbor-jobs")
    val_items = json.loads((KIT / "benchmark/splits/val/items.json").read_text())
    skill_dir = run_dir / "candidate/skills"
    results = candidate_rollout.run_split(
        "val", val_items, skill_dir=skill_dir, out_dir=run_dir / "candidate-val", candidate_id=audit["candidate_id"]
    )
    candidate = {str(r["id"]): int(r["hard"]) for r in results}
    if set(candidate) != expected:
        raise ValueError("candidate Val result IDs do not match official Val split")
    fixed = sorted(k for k in expected if baseline[k] == 0 and candidate[k] == 1)
    regressed = sorted(k for k in expected if baseline[k] == 1 and candidate[k] == 0)
    baseline_acc = sum(baseline.values()) / len(baseline)
    candidate_acc = sum(candidate.values()) / len(candidate)
    baseline_quality = best_state.get("val_quality") or {
        "execution_error_trials": sum(bool(row.get("execution_error")) for row in baseline_records),
        "zero_response_trials": sum(
            int(row.get("input_tokens") or 0) == 0 and int(row.get("output_tokens") or 0) == 0
            for row in baseline_records
        ),
        "terminal_model_error_trials": sum(bool(terminal_model_error(row.get("trace") or {})) for row in baseline_records),
    }
    candidate_quality = {
        "execution_error_trials": sum(bool(row.get("execution_error")) for row in results),
        "zero_response_trials": sum(bool(row.get("model_unavailable")) for row in results),
        "terminal_model_error_trials": sum(bool(row.get("terminal_model_error")) for row in results),
    }
    comparison_clean = not any(baseline_quality.values()) and not any(candidate_quality.values())
    candidate_text = (run_dir / "candidate/skill.md").read_text(encoding="utf-8")
    gate = evaluate_gate(candidate_text, candidate_acc, "", baseline_acc, "", baseline_acc, 0, 1, metric="hard")
    accepted = comparison_clean and candidate_acc > baseline_acc
    generation_tokens = int(audit.get("total_skill_generation_tokens", 0))

    run_dirs = sorted(
        p
        for p in (run_dir / "harbor-jobs" / audit["candidate_id"] / "val").glob("*/20*")
        if p.is_dir()
    )
    eval_job = run_dirs[-1] if run_dirs else None
    summary = (
        json.loads((eval_job / "summary.json").read_text()) if eval_job and (eval_job / "summary.json").exists() else {}
    )
    detailed_errors = _harbor_error_counts(eval_job, eval_job / "traces.jsonl", summary) if eval_job else {}
    decision = {
        "stage": "decided",
        "candidate_id": audit["candidate_id"],
        "baseline_val_accuracy": baseline_acc,
        "candidate_val_accuracy": candidate_acc,
        "score_gain": candidate_acc - baseline_acc,
        "score_gain_per_1m_generation_tokens": ((candidate_acc - baseline_acc) / (generation_tokens / 1_000_000))
        if generation_tokens and comparison_clean
        else None,
        "accept": accepted,
        "decision": "INCONCLUSIVE_MODEL_ERRORS" if not comparison_clean else "ACCEPT" if accepted else "REJECT",
        "baseline_quality": baseline_quality,
        "candidate_quality": candidate_quality,
        "gate_action": gate.action,
        "fixed_cases": fixed,
        "regressed_cases": regressed,
        "fixed_count": len(fixed),
        "regressed_count": len(regressed),
        "net_gain_cases": len(fixed) - len(regressed),
        "skill_length_chars": len(candidate_text),
        "skill_length_lines": len(candidate_text.splitlines()),
        "candidate_val_by_id": candidate,
        "baseline_val_by_id": baseline,
        "target_usage": {
            "input_tokens_including_cache": int(summary.get("input_tokens", 0)),
            "cached_tokens_subset": int(summary.get("cache_tokens", 0)),
            "output_tokens": int(summary.get("output_tokens", 0)),
            "reasoning_tokens_subset_of_output": int(summary.get("reasoning_tokens", 0)),
            "total_tokens": int(summary.get("input_tokens", 0)) + int(summary.get("output_tokens", 0)),
            "wall_time_seconds": summary.get("wall_sec"),
            **detailed_errors,
        },
        "optimizer_token_usage": audit.get("optimizer_token_usage", {}),
        "total_skill_generation_tokens": generation_tokens,
        "skill_trigger_rate": None,
    }
    (run_dir / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n")
    audit.update(stage="decided", decision=decision["decision"], val_job_dir=str(eval_job) if eval_job else None)
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    if accepted:
        best_root = run_dir.parent / "best"
        best_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill_dir, best_root / "skills", dirs_exist_ok=True)
        shutil.copy2(run_dir / "candidate/skill.md", best_root / "best_skill.md")
        (best_root / "best.json").write_text(
            json.dumps(
                {
                    "candidate_id": audit["candidate_id"],
                    "val_accuracy": candidate_acc,
                    "skill_sha256": audit["skill_sha256"],
                    "val_by_id": candidate,
                    "val_quality": candidate_quality,
                },
                indent=2,
            )
            + "\n"
        )
    else:
        # A rejected first candidate must leave a concrete R0 Best Skill so
        # later rounds can resume from the unchanged initial skill.
        _seed_best_from_initial(run_dir.parent / "best", baseline_acc)
        state_path = run_dir.parent / "best/best.json"
        state = json.loads(state_path.read_text())
        state.setdefault("val_by_id", baseline)
        state.setdefault("val_quality", baseline_quality)
        state_path.write_text(json.dumps(state, indent=2) + "\n")
        if comparison_clean:
            rejected_path = run_dir / "rejected_edit_buffer.json"
            rejected_path.write_text(
                json.dumps(
                    {
                        "candidate_id": audit["candidate_id"],
                        "reason": "strict Accuracy Gate did not improve Val",
                        "baseline_accuracy": baseline_acc,
                        "candidate_accuracy": candidate_acc,
                        "patch": json.loads((run_dir / "select/selected-patch.json").read_text()),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
    return decision


def run_baseline(split: str, jobs_dir: Path, n: int | None = None) -> int:
    assert_real_run_ready()
    target_proxy = proxy_credentials("target")
    models = read_models()
    command = [
        str(KIT / "run.sh"),
        "--bench",
        f"{benchmark_name()}-{split}",
        "--reasoning",
        "off",
        "--model-id",
        models["deepseek-v4-flash"],
        "--base-url",
        target_proxy.base_url,
        "--jobs-dir",
        str(jobs_dir),
    ]
    if n is not None:
        command.extend(["--n", str(n)])
    child_env = dict(__import__("os").environ)
    child_env["API_KEY"] = target_proxy.token
    code = subprocess.call(command, cwd=WORKSPACE, env=child_env)
    if code != 0:
        return code
    runs = sorted(Path(jobs_dir).glob("*/traces.jsonl"))
    if len(runs) != 1:
        raise RuntimeError(f"expected exactly one completed run under {jobs_dir}; found {len(runs)}")
    export = KIT / "workspace/traces" / f"{benchmark_name()}-{split}-baseline-nothink.jsonl"
    export.parent.mkdir(parents=True, exist_ok=True)
    if export.exists():
        raise FileExistsError(f"refusing to overwrite existing trace export: {export}")
    shutil.copy2(runs[0], export)
    print(f"copied official Harbor ATIF traces to {export}")
    return 0


def _search_initialize_best(
    run_root: Path,
    *,
    initial_skill: str = "",
    no_skill: bool = False,
    val_trace: str = "",
) -> Path:
    best_root = run_root / "best"
    best_skill = best_root / "best_skill.md"
    source = Path(initial_skill).expanduser().resolve() if initial_skill else _initial_skill_path()
    if not best_skill.is_file():
        best_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, best_skill)
    text = best_skill.read_text(encoding="utf-8")
    skill_hash = hashlib.sha256(text.encode()).hexdigest()
    best_root.mkdir(parents=True, exist_ok=True)
    if not no_skill:
        package_skill(text, best_root / "skills")
    state_path = best_root / "best.json"
    if state_path.is_file():
        old = json.loads(state_path.read_text(encoding="utf-8"))
        if (
            old.get("skill_sha256") == skill_hash
            and old.get("skill_enabled", True) == (not no_skill)
            and old.get("val_by_id")
        ):
            return best_skill
    val_items = json.loads((KIT / "benchmark/splits/val/items.json").read_text(encoding="utf-8"))
    candidate_id = f"best-init-val-{skill_hash[:12]}"
    if val_trace:
        records = load_records(Path(val_trace).expanduser().resolve())
        expected = {str(row["id"]) for row in val_items}
        by_id = {str(row["case_id"]): int(float(row.get("reward", 0)) >= 1.0) for row in records}
        if len(records) != len(expected) or set(by_id) != expected:
            raise ValueError("initial Val trace must contain exactly the official full Val split")
        val_quality = {
            "execution_error_trials": sum(bool(row.get("execution_error")) for row in records),
            "zero_response_trials": sum(
                int(row.get("input_tokens") or 0) == 0 and int(row.get("output_tokens") or 0) == 0
                for row in records
            ),
            "terminal_model_error_trials": sum(bool(terminal_model_error(row.get("trace") or {})) for row in records),
        }
    else:
        results = HarborKitRollout(KIT, run_root / "harbor-jobs").run_split(
            "val", val_items, skill_dir=None if no_skill else best_root / "skills",
            out_dir=best_root / "val-rollout", candidate_id=candidate_id,
        )
        by_id = {str(row["id"]): int(row["hard"]) for row in results}
        val_quality = {
            "execution_error_trials": sum(bool(row.get("execution_error")) for row in results),
            "zero_response_trials": sum(bool(row.get("model_unavailable")) for row in results),
            "terminal_model_error_trials": sum(bool(row.get("terminal_model_error")) for row in results),
        }
    state_path.write_text(
        json.dumps({
            "candidate_id": "R0",
            "val_accuracy": sum(by_id.values()) / len(by_id),
            "skill_sha256": skill_hash,
            "skill_enabled": not no_skill,
            "val_by_id": by_id,
            "val_quality": val_quality,
            "source": "official Harbor Val baseline trace" if val_trace else "official Harbor Val run of exact current Best",
            "harbor_candidate_id": candidate_id,
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    return best_skill


def _prior_clean_train_rollout(
    run_root: Path, candidate_id: str, skill_sha256: str | None,
    concurrent: int, max_retries: int, expected: set[str],
) -> tuple[str, Path] | None:
    """Reuse a scored Train rollout of the same Best, never a Val/Test result."""
    jobs = run_root / "harbor-jobs"
    prior = sorted(jobs.glob("C[0-9][0-9][0-9]-*-train/train/*/run_manifest.json"), reverse=True)
    for manifest_path in prior:
        job_candidate = manifest_path.parents[2].name
        if job_candidate.split("-", 1)[0] >= candidate_id:
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            request = json.loads((manifest_path.parent / "run_request.json").read_text(encoding="utf-8"))
            trace_path = Path(manifest["trace_file"])
            job_dir = Path(manifest["job_dir"])
            if not (
                manifest.get("complete") is True
                and manifest.get("split") == "train"
                and manifest.get("candidate_sha256") == skill_sha256
                and int(request.get("concurrent", -1)) == concurrent
                and int(request.get("max_retries", -1)) == max_retries
                and job_dir.joinpath("summary.json").is_file()
            ):
                continue
            records = load_records(trace_path)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if len(records) != len(expected) or {str(row.get("case_id")) for row in records} != expected:
            continue
        if any(
            row.get("execution_error")
            or (int(row.get("input_tokens") or 0) == 0 and int(row.get("output_tokens") or 0) == 0)
            or terminal_model_error(row.get("trace") or {})
            for row in records
        ):
            continue
        return job_candidate, trace_path
    return None


def search_candidates(args: argparse.Namespace) -> list[dict]:
    """Run the bounded Train→Reflect→Train-screen→Val candidate loop."""
    from trace2skill.campaign import run_candidate_sequence

    assert_real_run_ready()
    run_root = Path(args.run_root).resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    if args.initial_no_skill:
        os.environ["TRACE2SKILL_INITIAL_NO_SKILL"] = "1"
    if args.initial_skill:
        os.environ["TRACE2SKILL_INITIAL_SKILL"] = str(Path(args.initial_skill).resolve())
    _search_initialize_best(
        run_root,
        initial_skill=args.initial_skill,
        no_skill=args.initial_no_skill,
        val_trace=args.initial_val_trace,
    )
    initial_best_state = json.loads((run_root / "best/best.json").read_text(encoding="utf-8"))
    if any((initial_best_state.get("val_quality") or {}).values()):
        raise RuntimeError("official Val baseline has execution/zero-response trials; rerun the complete Val split before candidate selection")
    existing = sorted(p for p in run_root.glob("C[0-9][0-9][0-9]") if p.is_dir())
    completed = set()
    prior_outcomes: list[dict] = []
    state_file = run_root / "search_state.json"
    if args.resume and state_file.is_file():
        prior_state = json.loads(state_file.read_text(encoding="utf-8"))
        prior_outcomes = list(prior_state.get("completed", []))
        completed = {str(x.get("candidate_id")) for x in prior_outcomes}
    if args.resume:
        for candidate_dir in existing:
            config_path = candidate_dir / "run_config.json"
            if candidate_dir.name not in completed and config_path.is_file():
                config = json.loads(config_path.read_text(encoding="utf-8"))
                if config.get("stage") in {"decided", "train_screen_rejected", "train_screen_inconclusive", "no_candidate"}:
                    completed.add(candidate_dir.name)
                    prior_outcomes.append({
                        "candidate_id": candidate_dir.name,
                        "decision": config.get("decision", config.get("stage", "COMPLETED")),
                        "generation_tokens": config.get("total_skill_generation_tokens", 0),
                    })
    if existing and not args.resume:
        raise FileExistsError("search run root already has candidate checkpoints; pass --resume or use a new root")
    # Resume completed checkpoints without skipping an interrupted candidate.
    # Incomplete directories are retried with evolve --resume and Harbor's
    # per-stage manifests provide the idempotency boundary.
    candidate_ids = [f"C{i:03d}" for i in range(1, int(args.max_candidates) + 1) if f"C{i:03d}" not in completed]
    prior_tokens = sum(
        int((p / "run_config.json").exists() and json.loads((p / "run_config.json").read_text()).get("total_skill_generation_tokens", 0))
        for p in existing
    )
    search_spent = prior_tokens

    def run_one(candidate_id: str) -> dict:
        nonlocal search_spent
        os.environ["TRACE2SKILL_GENERATION_TOKEN_BUDGET"] = str(max(0, int(args.token_budget) - search_spent))
        best_skill = run_root / "best/best_skill.md"
        best_state = json.loads((run_root / "best/best.json").read_text(encoding="utf-8"))
        best_skill_dir = run_root / "best/skills"
        if best_state.get("skill_enabled", True) and not best_skill_dir.is_dir():
            package_skill(best_skill.read_text(encoding="utf-8"), run_root / "best/skills")
        round_dir = run_root / candidate_id
        runner = HarborKitRollout(KIT, run_root / "harbor-jobs")
        train_items = json.loads((KIT / "benchmark/splits/train/items.json").read_text(encoding="utf-8"))
        best_train_dir = round_dir / "train-current-best"
        baseline_rows = (
            load_records(Path(args.initial_train_trace).resolve())
            if candidate_id == "C001" and args.initial_train_trace and not best_state.get("skill_enabled", True)
            else []
        )
        baseline_reusable = bool(baseline_rows) and all(
            not row.get("execution_error")
            and (int(row.get("input_tokens") or 0) > 0 or int(row.get("output_tokens") or 0) > 0)
            and not terminal_model_error(row.get("trace") or {})
            for row in baseline_rows
        )
        best_train = None
        best_sha = (
            hashlib.sha256(next(best_skill_dir.glob("*/SKILL.md")).read_bytes()).hexdigest()
            if best_state.get("skill_enabled", True) else None
        )
        reusable = None if baseline_rows else _prior_clean_train_rollout(
            run_root, candidate_id, best_sha, runner.concurrent, runner.max_retries,
            {str(row["id"]) for row in train_items},
        )
        if reusable:
            prior_job_id, reflect_trace = reusable
            best_train = runner.run_split(
                "train", train_items,
                skill_dir=best_skill_dir if best_state.get("skill_enabled", True) else None,
                out_dir=best_train_dir, candidate_id=prior_job_id,
            )
            round_dir.mkdir(parents=True, exist_ok=True)
            (round_dir / "train_reuse.json").write_text(json.dumps({
                "source_candidate_job": prior_job_id,
                "source_trace": str(reflect_trace),
                "best_skill_sha256": best_sha,
                "reason": "same official full Train split, clean execution, unchanged Best SHA and Harbor settings",
            }, indent=2) + "\n", encoding="utf-8")
        elif baseline_rows:
            # The supplied full baseline can feed the first Reflect. If its
            # scores contain infrastructure failures, defer a fresh paired
            # Best rollout until an actual candidate exists.
            reflect_trace = Path(args.initial_train_trace).resolve()
            if baseline_reusable:
                best_train = convert_trace_file(reflect_trace, "train", best_train_dir)
        else:
            best_train = runner.run_split(
                "train", train_items,
                skill_dir=best_skill_dir if best_state.get("skill_enabled", True) else None,
                out_dir=best_train_dir,
                candidate_id=f"{candidate_id}-best-train",
            )
            manifests = sorted((run_root / "harbor-jobs" / f"{candidate_id}-best-train" / "train").glob("*/run_manifest.json"))
            if not manifests:
                raise FileNotFoundError("current-best Harbor Train rollout did not save its run manifest")
            reflect_trace = Path(json.loads(manifests[-1].read_text())["trace_file"])
        evolve_args = argparse.Namespace(
            run_dir=str(round_dir), train_trace=str(reflect_trace), initial_skill=str(best_skill),
            minibatch_size=args.minibatch_size, edit_budget=args.edit_budget, failure_only=False,
            resume=round_dir.exists(),
        )
        reflect_recovered_without_usage = (
            (round_dir / "reflect/raw-patches.json").is_file()
            and not (round_dir / "run_config.json").is_file()
        )
        audit = evolve(evolve_args)
        if reflect_recovered_without_usage:
            # A prior process may have completed live Reflect calls and saved
            # their patches before a later deterministic stage failed. The
            # response usage existed only in that process's in-memory ledger,
            # so mark the resumed candidate's usage as a lower bound instead
            # of silently treating the resumed ledger as complete.
            audit["optimizer_usage_complete"] = False
            audit["optimizer_usage_gap"] = "Reflect completed in an earlier process; per-response usage was not checkpointed"
            (round_dir / "run_config.json").write_text(
                json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        candidate_tokens = int(audit.get("total_skill_generation_tokens", 0))
        if audit.get("stage") == "no_candidate":
            return {
                "candidate_id": candidate_id,
                "decision": "NO_CANDIDATE",
                "generation_tokens": candidate_tokens,
                "reason": "risk filter or native selector produced no eligible edit; no rollout performed",
            }
        if best_train is None:
            best_train = runner.run_split(
                "train", train_items,
                skill_dir=best_skill_dir if best_state.get("skill_enabled", True) else None,
                out_dir=best_train_dir,
                candidate_id=f"{candidate_id}-best-train",
            )
        search_spent += candidate_tokens
        candidate_train_dir = round_dir / "candidate-train"
        candidate_train = runner.run_split(
            "train", train_items, skill_dir=round_dir / "candidate/skills", out_dir=candidate_train_dir,
            candidate_id=f"{candidate_id}-candidate-train",
        )
        before = {str(r["id"]): int(r["hard"]) for r in best_train}
        after = {str(r["id"]): int(r["hard"]) for r in candidate_train}
        fixed = sorted(k for k in before if not before[k] and after[k])
        regressed = sorted(k for k in before if before[k] and not after[k])
        train_delta = sum(after.values()) / len(after) - sum(before.values()) / len(before)
        screen = {
            "candidate_id": candidate_id,
            "best_train_accuracy": sum(before.values()) / len(before),
            "candidate_train_accuracy": sum(after.values()) / len(after),
            "delta": train_delta,
            "fixed_cases": fixed,
            "regressed_cases": regressed,
            "candidate_generation_tokens": audit.get("total_skill_generation_tokens", 0),
            "best_execution_or_zero_response_trials": sum(
                bool(r.get("execution_error") or r.get("model_unavailable") or r.get("terminal_model_error")) for r in best_train
            ),
            "candidate_execution_or_zero_response_trials": sum(
                bool(r.get("execution_error") or r.get("model_unavailable") or r.get("terminal_model_error")) for r in candidate_train
            ),
        }
        (round_dir / "train_screen.json").write_text(json.dumps(screen, indent=2) + "\n")
        if screen["best_execution_or_zero_response_trials"] or screen["candidate_execution_or_zero_response_trials"]:
            audit.update(stage="train_screen_inconclusive", decision="INCONCLUSIVE_TRAIN_ERRORS")
            (round_dir / "run_config.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
            return {"candidate_id": candidate_id, "decision": "INCONCLUSIVE_TRAIN_ERRORS", "generation_tokens": candidate_tokens}
        if train_delta < -float(args.train_regression_tolerance):
            rejected = {
                "candidate_id": candidate_id,
                "reason": "Train regression screen failed",
                "train_screen": screen,
                "patch": json.loads((round_dir / "select/selected-patch.json").read_text()),
            }
            (round_dir / "rejected_edit_buffer.json").write_text(json.dumps(rejected, indent=2) + "\n")
            audit.update(stage="train_screen_rejected", decision="REJECT_TRAIN_SCREEN")
            (round_dir / "run_config.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
            return {"candidate_id": candidate_id, "decision": "REJECT_TRAIN_SCREEN", "generation_tokens": candidate_tokens}
        decision = evaluate_candidate(argparse.Namespace(run_dir=str(round_dir), val_trace=None))
        return {"candidate_id": candidate_id, "decision": decision["decision"], "generation_tokens": candidate_tokens, "val_accuracy": decision["candidate_val_accuracy"]}

    outcomes = run_candidate_sequence(candidate_ids, run_one, max(0, int(args.token_budget) - prior_tokens))
    all_outcomes = prior_outcomes + outcomes
    state = {"run_root": str(run_root), "candidate_limit": int(args.max_candidates), "token_budget": int(args.token_budget), "completed": all_outcomes}
    (run_root / "search_state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    return outcomes


def run_pipeline(run_id: str) -> None:
    model_check(ROOT / "results/model_config_report.json")
    print("model checks passed; starting 3-task Harbor/Pi smoke")
    smoke_dir = KIT / "workspace/runs" / f"train-smoke-nothink-{run_id}"
    code = subprocess.call(
        [
            str(KIT / "run.sh"),
            "--bench",
            "spreadsheetbench-train",
            "--reasoning",
            "off",
            "--n",
            "3",
            "--jobs-dir",
            str(smoke_dir),
        ],
        cwd=WORKSPACE,
    )
    if code:
        raise SystemExit(f"Smoke failed (exit={code}); full baselines were not started")
    for split in ("train", "val"):
        jobs = KIT / "workspace/runs" / f"{split}-baseline-nothink-{run_id}"
        code = run_baseline(split, jobs)
        if code:
            raise SystemExit(f"{split} baseline failed (exit={code})")
    run_dir = ROOT / "results" / run_id
    args = argparse.Namespace(
        run_dir=str(run_dir),
        train_trace=None,
        initial_skill=str(ROOT / "src/skillopt/envs/harbor_pi/skills/initial.md"),
        minibatch_size=8,
        edit_budget=3,
        failure_only=False,
        resume=False,
    )
    audit = evolve(args)
    result = evaluate_candidate(argparse.Namespace(run_dir=str(run_dir), val_trace=None))
    print(
        json.dumps(
            {
                "models_verified": True,
                "optimizer": audit.get("optimizer_token_usage"),
                "decision": result.get("decision"),
                "val_accuracy": result.get("candidate_val_accuracy"),
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("model-check")
    check.add_argument("--out", default=str(ROOT / "results/model_config_report.json"))
    base = sub.add_parser("baseline")
    base.add_argument("--split", choices=["train", "val"], required=True)
    base.add_argument("--jobs-dir", required=True)
    base.add_argument("--n", type=int)
    conv = sub.add_parser("convert")
    conv.add_argument("--split", choices=["train", "val"], required=True)
    conv.add_argument("--trace")
    conv.add_argument("--out-dir", required=True)
    evo = sub.add_parser("evolve")
    evo.add_argument("--run-dir", required=True)
    evo.add_argument("--train-trace")
    evo.add_argument("--initial-skill")
    evo.add_argument("--minibatch-size", type=int, default=8)
    evo.add_argument("--edit-budget", type=int, default=1)
    evo.add_argument("--failure-only", action="store_true", help=argparse.SUPPRESS)
    evo.add_argument("--resume", action="store_true")
    search = sub.add_parser("search", help="bounded multi-candidate Train→Val evolution")
    search.add_argument("--run-root", required=True)
    search.add_argument("--max-candidates", type=int, default=3)
    search.add_argument("--initial-train-trace", help="reuse an existing full official Train trace for C001 Reflect")
    search.add_argument("--initial-val-trace", help="use an existing full official Val baseline trace")
    search.add_argument("--initial-skill", help="initial Skill text; defaults to the benchmark-specific starter")
    search.add_argument("--initial-no-skill", action="store_true", help="use no Skill as R0 Best while Reflect starts from a blank Skill")
    search.add_argument("--token-budget", type=int, default=900000)
    search.add_argument("--train-regression-tolerance", type=float, default=0.05)
    search.add_argument("--minibatch-size", type=int, default=8)
    search.add_argument("--edit-budget", type=int, default=1)
    search.add_argument("--resume", action="store_true")
    ev = sub.add_parser("evaluate")
    ev.add_argument("--run-dir", required=True)
    ev.add_argument("--val-trace")
    exp = sub.add_parser("export-best")
    exp.add_argument("--run-dir", required=True)
    exp.add_argument("--out", required=True)
    tok = sub.add_parser("tokens")
    tok.add_argument("--run-dir", required=True)
    comp = sub.add_parser("compare")
    comp.add_argument("--run-dir", required=True)
    pipe = sub.add_parser("pipeline")
    pipe.add_argument("--run-id", default=time.strftime("R1-%Y%m%d-%H%M%S"))
    args = parser.parse_args()
    if args.command == "model-check":
        report = model_check(Path(args.out))
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.command == "baseline":
        raise SystemExit(run_baseline(args.split, Path(args.jobs_dir).resolve(), args.n))
    elif args.command == "convert":
        trace = Path(args.trace).resolve() if args.trace else _trace_file(args.split)
        results = convert_trace_file(trace, args.split, Path(args.out_dir).resolve())
        print(
            json.dumps({"samples": len(results), "failed": sum(not r["hard"] for r in results), "output": args.out_dir})
        )
    elif args.command == "evolve":
        print(json.dumps(evolve(args), ensure_ascii=False, indent=2))
    elif args.command == "search":
        print(json.dumps(search_candidates(args), ensure_ascii=False, indent=2))
    elif args.command == "evaluate":
        print(json.dumps(evaluate_candidate(args), ensure_ascii=False, indent=2))
    elif args.command == "export-best":
        run_dir = Path(args.run_dir).resolve()
        decision = json.loads((run_dir / "decision.json").read_text())
        target = Path(args.out).resolve()
        source = run_dir / "candidate/skills" if decision.get("accept") else run_dir.parent / "best/skills"
        if not source.is_dir():
            raise FileNotFoundError(f"best Skill package is missing: {source}")
        shutil.copytree(source, target, dirs_exist_ok=True)
        print(target)
    elif args.command == "tokens":
        p = Path(args.run_dir).resolve() / "decision.json"
        payload = (
            json.loads(p.read_text())
            if p.exists()
            else json.loads((Path(args.run_dir) / "run_config.json").read_text())
        )
        opt = payload.get("optimizer_token_usage", {}).get("_total", {})
        target = payload.get("target_usage", {})
        print(
            json.dumps(
                {
                    "optimizer_input_tokens": opt.get("prompt_tokens", 0),
                    "optimizer_output_tokens": opt.get("completion_tokens", 0),
                    "optimizer_reasoning_tokens_subset": opt.get("reasoning_tokens", 0),
                    "optimizer_cached_tokens_subset": opt.get("cached_tokens", 0),
                    "optimizer_total_tokens": opt.get("total_tokens", 0),
                    "total_skill_generation_tokens": payload.get(
                        "total_skill_generation_tokens", opt.get("total_tokens", 0)
                    ),
                    "target_input_tokens_including_cache": target.get("input_tokens_including_cache", 0),
                    "target_cached_tokens_subset": target.get("cached_tokens_subset", 0),
                    "target_output_tokens": target.get("output_tokens", 0),
                    "target_reasoning_tokens_subset": target.get("reasoning_tokens_subset_of_output", 0),
                    "total_harbor_evaluation_tokens": target.get("total_tokens", 0),
                },
                indent=2,
            )
        )
    elif args.command == "compare":
        payload = json.loads((Path(args.run_dir).resolve() / "decision.json").read_text())
        print(
            json.dumps(
                {
                    k: payload[k]
                    for k in (
                        "baseline_val_accuracy",
                        "candidate_val_accuracy",
                        "fixed_count",
                        "regressed_count",
                        "net_gain_cases",
                        "decision",
                        "skill_length_chars",
                        "total_skill_generation_tokens",
                        "optimizer_token_usage",
                        "target_usage",
                    )
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "pipeline":
        run_pipeline(args.run_id)


if __name__ == "__main__":
    main()
