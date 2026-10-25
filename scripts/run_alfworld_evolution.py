#!/usr/bin/env python3
"""Run the Round 2 ALFWorld baseline, smoke checks, and one bounded evolution.

Credentials are read from the operator's existing model.txt and kept in process
environment / the private Kit kit.env; they are never printed or placed in argv.
"""
from __future__ import annotations

import json
import hashlib
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

SUBMISSION = Path(__file__).resolve().parents[1]
WORKSPACE = Path(os.environ.get("TRACE2SKILL_WORKSPACE", SUBMISSION.parents[1])).expanduser().resolve()
KIT = Path(os.environ.get("HARBOR_KIT_ROOT", SUBMISSION.parent / "benchmarks/alfworld-v2-kit")).expanduser().resolve()
RUN_ROOT = SUBMISSION / "results/alfworld-v2-20261020-evolution"
MODEL_CONFIG = SUBMISSION / "configs/harbor_pi/default.yaml"


def parse_env_file(path: Path) -> dict[str, str]:
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        parsed = shlex.split(raw_value, comments=True)
        values[key.strip()] = parsed[0] if parsed else ""
    return values


def load_local_config() -> tuple[str, str, dict[str, str]]:
    key = os.environ.get("TRACE2SKILL_LOCAL_API_KEY", "")
    ids: dict[str, str] = {}
    model_file = WORKSPACE / "model.txt"
    for raw in (model_file.read_text(encoding="utf-8").splitlines() if model_file.is_file() else []):
        try:
            parts = shlex.split(raw)
        except ValueError:
            continue
        if not key and len(parts) >= 2 and parts[0] == "export" and parts[1].startswith("WQ_API_KEY="):
            key = parts[1].split("=", 1)[1]
        elif len(parts) >= 4 and parts[1] == "model_id" and parts[2] == "=":
            ids[parts[0]] = parts[3]
    kit_env = parse_env_file(KIT / "kit.env") if (KIT / "kit.env").is_file() else {}
    if not key:
        key = kit_env.get("API_KEY", "")
    if not key:
        raise RuntimeError("set TRACE2SKILL_LOCAL_API_KEY, or provide model.txt / private Kit kit.env")
    old_kit = WORKSPACE / "spreadsheetbench-harbor-kit-v3.3-layout2/kit.env"
    base_url = os.environ.get("TRACE2SKILL_LOCAL_BASE_URL", "")
    if not base_url and old_kit.is_file():
        base_url = parse_env_file(old_kit).get("KIT_BASE_URL", "")
    if not base_url:
        base_url = kit_env.get("KIT_BASE_URL", "")
    if not base_url.startswith("https://"):
        raise RuntimeError("set TRACE2SKILL_LOCAL_BASE_URL or provide a private HTTPS Kit base URL")
    if not ids:
        ids = yaml_models()
    return key, base_url, ids


def yaml_models() -> dict[str, str]:
    import yaml
    model = yaml.safe_load(MODEL_CONFIG.read_text(encoding="utf-8"))["model"]
    return {
        "kimi-k2.6": str(model["optimizer_openai_compatible_model"]),
        "deepseek-v4-flash": str(model["target_openai_compatible_model"]),
    }


def private_kit_env(key: str, base_url: str, target_model: str) -> None:
    text = "\n".join(
        [
            f"KIT_MODEL_ID={shlex.quote(target_model)}",
            "KIT_API='openai-completions'",
            f"KIT_BASE_URL={shlex.quote(base_url)}",
            f"API_KEY={shlex.quote(key)}",
            "HARBOR_CONTAINER_ENGINE='auto'",
            "",
        ]
    )
    path = KIT / "kit.env"
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)


def runtime_env(key: str, base_url: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "HARBOR_KIT_ROOT": str(KIT),
            "TRACE2SKILL_DIRECT_LOCAL": "1",
            "TRACE2SKILL_LOCAL_BASE_URL": base_url,
            "TRACE2SKILL_TARGET_BASE_URL": base_url,
            "TRACE2SKILL_OPTIMIZER_BASE_URL": base_url,
            "TRACE2SKILL_LOCAL_API_KEY": key,
            "TRACE2SKILL_TARGET_API_KEY": key,
            "TRACE2SKILL_OPTIMIZER_API_KEY": key,
            "TRACE2SKILL_HARBOR_CONCURRENT": "1",
            "TRACE2SKILL_HARBOR_MAX_RETRIES": "2",
            "TRACE2SKILL_GENERATION_TOKEN_BUDGET": "900000",
            "TRACE2SKILL_INITIAL_NO_SKILL": "1",
            "TRACE2SKILL_INITIAL_SKILL": str(SUBMISSION / "src/skillopt/envs/alfworld/skills/blank.md"),
            "API_KEY": key,
        }
    )
    return env


def run_logged(
    name: str, command: list[str], env: dict[str, str], *, cwd: Path,
    allowed_returncodes: tuple[int, ...] = (0,),
) -> int:
    logs = RUN_ROOT / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    logfile = logs / f"{name}.log"
    with logfile.open("w", encoding="utf-8") as stream:
        proc = subprocess.run(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, check=False)
    content = logfile.read_text(encoding="utf-8", errors="replace")
    for env_name, value in env.items():
        if env_name.endswith(("API_KEY", "_TOKEN")) and value:
            content = content.replace(value, "[REDACTED]")
    logfile.write_text(content, encoding="utf-8")
    if proc.returncode not in allowed_returncodes:
        raise RuntimeError(f"{name} failed (exit={proc.returncode}); inspect {logfile}")
    return proc.returncode


def model_probe(env: dict[str, str]) -> None:
    report_path = RUN_ROOT / "model_config_report.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        models = yaml_models()
        if (
            report.get("endpoint") == env["TRACE2SKILL_LOCAL_BASE_URL"]
            and report.get("target", {}).get("model_id") == models["deepseek-v4-flash"]
            and report.get("target", {}).get("thinking") == "off"
            and report.get("optimizer", {}).get("model_id") == models["kimi-k2.6"]
            and report.get("optimizer", {}).get("thinking") == "on"
            and report.get("optimizer", {}).get("max_completion_tokens_accepted") is True
            and report.get("optimizer", {}).get("skillopt_backend_probe", {}).get("wire_max_completion_tokens") == 90000
        ):
            return
    sys.path.insert(0, str(SUBMISSION / "src"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("trace2skill_cli", SUBMISSION / "scripts/trace2skill.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    module.model_check(report_path)


def run_harbor(name: str, bench: str, jobs: Path, key: str, base_url: str, target_model: str, *, n: int | None = None) -> Path:
    env = os.environ.copy()
    env["API_KEY"] = key
    jobs.mkdir(parents=True, exist_ok=True)
    run_dirs = sorted(path for path in jobs.iterdir() if path.is_dir())
    if len(run_dirs) > 1:
        raise RuntimeError(f"{name} has multiple Harbor runs; select a fresh jobs directory")
    command = [
        str(KIT / "run.sh"), "--bench", bench, "--reasoning", "off", "--concurrent", "1",
        "--model-id", target_model, "--base-url", base_url, "--jobs-dir", str(jobs),
    ]
    if n is not None:
        command.extend(["--n", str(n)])
    if not run_dirs:
        run_logged(name, command, env, cwd=KIT.parent, allowed_returncodes=(0, 4))
        run_dirs = sorted(path for path in jobs.iterdir() if path.is_dir())
    if len(run_dirs) != 1:
        raise RuntimeError(f"{name} did not produce exactly one Harbor run directory")
    job = run_dirs[0]
    summary_path = job / "summary.json"
    if not summary_path.is_file():
        raise RuntimeError(f"{name} has no official Harbor summary")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    expected = n if n is not None else len(json.loads((KIT / f"benchmark/splits/{'train' if bench.endswith('train') else 'val'}/items.json").read_text()))
    results = list(job.glob("*/result.json"))
    scored = (
        len(results) == expected
        and int(summary.get("n_trials", -1)) == expected
        and all(
            ((row.get("verifier_result") or {}).get("rewards") or {}).get("reward") is not None
            for path in results
            for row in [json.loads(path.read_text(encoding="utf-8"))]
        )
    )
    if not scored:
        raise RuntimeError(f"{name} has incomplete Harbor scores")
    exceptions = [
        path.parent.name for path in results
        if json.loads(path.read_text(encoding="utf-8")).get("exception_info")
    ]
    (job / "trace2skill_status.json").write_text(
        json.dumps({"scored_trials": len(results), "exception_trials": sorted(exceptions)}, indent=2) + "\n",
        encoding="utf-8",
    )
    trace = job / "traces.jsonl"
    if not trace.is_file():
        exporter = KIT / "results/export_traces.py"
        result = subprocess.run(
            [str(KIT / "workspace/.venv/bin/python"), str(exporter), "--job", str(job), "--output", str(trace)],
            cwd=KIT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode or not trace.is_file():
            raise RuntimeError(f"{name} official ATIF export failed")
    return trace


def main() -> None:
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    key, base_url, file_ids = load_local_config()
    models = yaml_models()
    if any(file_ids.get(name) != value for name, value in models.items()):
        raise RuntimeError("model.txt IDs do not match the active public model configuration")
    private_kit_env(key, base_url, models["deepseek-v4-flash"])
    env = runtime_env(key, base_url)
    os.environ.update(env)
    if not (KIT / "workspace/.venv/bin/harbor").is_file():
        raise RuntimeError("ALFWorld Kit is not initialized; run its setup.sh first")

    # Low-cost model probes only after Kit setup and direct local config validation.
    model_probe(env)
    smoke_runs = list((RUN_ROOT / "smoke-jobs").glob("*/summary.json"))
    if not smoke_runs:
        run_logged(
            "selfcheck",
            [str(KIT / "run.sh"), "--selfcheck", "--n", "6", "--concurrent", "1"],
            env, cwd=KIT.parent,
        )
    run_harbor("smoke", "alfworld-train", RUN_ROOT / "smoke-jobs", key, base_url, models["deepseek-v4-flash"], n=3)

    train_trace = run_harbor(
        "train-baseline", "alfworld-train", RUN_ROOT / "baseline/train-jobs", key, base_url,
        models["deepseek-v4-flash"],
    )
    val_trace = run_harbor(
        "val-baseline", "alfworld-val", RUN_ROOT / "baseline/val-jobs", key, base_url,
        models["deepseek-v4-flash"],
    )
    train_copy = RUN_ROOT / "baseline/train-no-skill.jsonl"
    val_copy = RUN_ROOT / "baseline/val-no-skill.jsonl"
    train_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(train_trace, train_copy)
    shutil.copy2(val_trace, val_copy)

    search = [
        sys.executable, str(SUBMISSION / "scripts/trace2skill.py"), "search",
        "--run-root", str(RUN_ROOT / "campaign"),
        "--initial-train-trace", str(train_copy),
        "--initial-val-trace", str(val_copy),
        "--initial-skill", str(SUBMISSION / "src/skillopt/envs/alfworld/skills/blank.md"),
        "--initial-no-skill", "--max-candidates", "2", "--token-budget", "900000",
        "--train-regression-tolerance", "0.05", "--minibatch-size", "8", "--edit-budget", "1",
    ]
    campaign = RUN_ROOT / "campaign"
    resuming = any(campaign.glob("C[0-9][0-9][0-9]")) or (campaign / "search_state.json").is_file()
    if resuming:
        search.append("--resume")
    run_logged("evolution-resume" if resuming else "evolution", search, env, cwd=SUBMISSION)
    best_state = json.loads((RUN_ROOT / "campaign/best/best.json").read_text(encoding="utf-8"))
    exported_skill = None
    if best_state.get("skill_enabled") and best_state.get("candidate_id") != "R0":
        best_skills = RUN_ROOT / "campaign/best/skills"
        for source in sorted(best_skills.glob("*/SKILL.md")):
            destination = SUBMISSION / "skills" / source.parent.name / "SKILL.md"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            exported_skill = {"path": str(destination), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}
    (RUN_ROOT / "execution_status.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "benchmark": "ALFWorld Round 2",
                "run_root": str(RUN_ROOT),
                "target_model": models["deepseek-v4-flash"],
                "target_thinking": "off",
                "optimizer_model": models["kimi-k2.6"],
                "optimizer_thinking": "on",
                "test_executed": False,
                "candidate_limit": 2,
                "best_candidate_id": best_state.get("candidate_id"),
                "best_val_accuracy": best_state.get("val_accuracy"),
                "exported_skill": exported_skill,
                "concurrency": 1,
                "credential_values_persisted_in_results": False,
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
