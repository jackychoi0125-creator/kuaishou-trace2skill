"""Harbor Kit execution wrapper; all grades and traces come from Harbor."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from .security import proxy_credentials
from .trace_converter import convert_record, normalize_case_id


class HarborKitRollout:
    def __init__(
        self,
        kit_root: str | Path,
        jobs_root: str | Path,
        *,
        concurrent: int | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.kit_root = Path(kit_root).resolve()
        self.jobs_root = Path(jobs_root).resolve()
        self.concurrent = concurrent or int(os.environ.get("TRACE2SKILL_HARBOR_CONCURRENT", "3"))
        self.max_retries = max_retries if max_retries is not None else int(
            os.environ.get("TRACE2SKILL_HARBOR_MAX_RETRIES", "2")
        )
        if self.concurrent < 1:
            raise ValueError("Harbor concurrency must be at least 1")
        if self.max_retries < 0:
            raise ValueError("Harbor max_retries cannot be negative")
        self.run_script = self.kit_root / "run.sh"
        if not self.run_script.is_file():
            raise FileNotFoundError(self.run_script)
        self.supports_max_retries = "--max-retries" in self.run_script.read_text(encoding="utf-8", errors="replace")
        split_manifest = self.kit_root / "benchmark/splits/split_manifest.json"
        self.benchmark = "spreadsheetbench"
        if split_manifest.is_file():
            try:
                source = str(json.loads(split_manifest.read_text(encoding="utf-8")).get("benchmark", ""))
                if source.casefold() == "alfworld":
                    self.benchmark = "alfworld"
            except (OSError, ValueError):
                pass

    def _bench_name(self, split: str) -> str:
        return f"{self.benchmark}-{split}"

    def run_split(
        self, split: str, items: list[dict], *, skill_dir: str | Path | None, out_dir: str | Path, candidate_id: str
    ) -> list[dict]:
        split = {"valid_seen": "val", "selection": "val", "valid_unseen": "test"}.get(split, split)
        if split not in {"train", "val", "test"}:
            raise ValueError(f"unsupported Harbor split {split!r}")
        manifest_path = self.kit_root / "benchmark" / "splits" / split / "items.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = {str(row["id"]) for row in manifest}
        requested = {str(row["id"]) for row in items}
        if expected != requested or len(expected) != len(items):
            raise ValueError(
                "Harbor Kit only supports complete official split rollouts; refusing partial/duplicate IDs"
            )

        skill_hash = None
        if skill_dir:
            skill_root = Path(skill_dir)
            skill_candidates = [skill_root / "SKILL.md", *sorted(skill_root.glob("*/SKILL.md"))]
            skill_file = next((p for p in skill_candidates if p.is_file()), None)
            if skill_file is None:
                raise FileNotFoundError(f"no SKILL.md in candidate skill directory: {skill_dir}")
            skill_hash = hashlib.sha256(skill_file.read_bytes()).hexdigest()

        # Resume only the exact same candidate/split whose own official Harbor
        # job completed and exported every trace. Never share results across IDs.
        for manifest_path in sorted((self.jobs_root / candidate_id / split).glob("*/run_manifest.json")):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                trace = Path(manifest["trace_file"])
                job_dir = Path(manifest["job_dir"])
                records = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines() if line.strip()]
                for record in records:
                    record["case_id"] = normalize_case_id(record.get("case_id"))
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
            if (
                manifest.get("complete") is True
                and manifest.get("candidate_sha256") == skill_hash
                and job_dir.joinpath("summary.json").is_file()
                and {str(r.get("case_id")) for r in records} == expected
                and len(records) == len(expected)
            ):
                return self._convert_records(records, Path(out_dir), split)

        # Harbor may finish and score every trial, then fail in the Kit's
        # separate metadata probe before summary/ATIF export. Recover those
        # official artifacts without rerunning any model task. Incomplete
        # trial sets never pass this gate.
        for prior_root in sorted((self.jobs_root / candidate_id / split).glob("*")):
            request_path = prior_root / "run_request.json"
            if not request_path.is_file() or (prior_root / "run_manifest.json").is_file():
                continue
            try:
                request = json.loads(request_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if request.get("candidate_sha256") != skill_hash or request.get("expected_case_count") != len(expected):
                continue
            for prior_job in sorted(p for p in prior_root.iterdir() if p.is_dir()):
                try:
                    prior_trials = [json.loads(p.read_text(encoding="utf-8")) for p in prior_job.glob("*/result.json")]
                except (OSError, ValueError):
                    continue
                if (
                    len(prior_trials) != len(expected)
                    or {normalize_case_id(r.get("task_name")) for r in prior_trials} != expected
                    or not all(r.get("finished_at") and ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward") is not None for r in prior_trials)
                ):
                    continue
                summary_path = prior_job / "summary.json"
                if not summary_path.is_file():
                    summarized = subprocess.run(
                        [str(self.kit_root / "workspace/.venv/bin/python"), str(self.kit_root / "results/summarize.py"), "--job", str(prior_job)],
                        cwd=self.kit_root, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                        text=True, check=False,
                    )
                    if summarized.returncode != 0 or not summary_path.is_file():
                        raise RuntimeError(f"official Harbor summary recovery failed for {prior_job}")
                trace_path = prior_job / "traces.jsonl"
                if not trace_path.is_file():
                    exported = subprocess.run(
                        [str(self.kit_root / "workspace/.venv/bin/python"), str(self.kit_root / "results/export_traces.py"), "--job", str(prior_job), "--output", str(trace_path)],
                        cwd=self.kit_root, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                        text=True, check=False,
                    )
                    if exported.returncode != 0 or not trace_path.is_file():
                        raise RuntimeError(f"official Harbor trace recovery failed for {prior_job}")
                records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
                for record in records:
                    record["case_id"] = normalize_case_id(record.get("case_id"))
                if len(records) != len(expected) or {r["case_id"] for r in records} != expected:
                    raise RuntimeError("recovered Harbor ATIF does not match the official full split")
                (prior_root / "run_manifest.json").write_text(json.dumps({
                    "candidate_id": candidate_id, "split": split,
                    "job_dir": str(prior_job), "trace_file": str(trace_path),
                    "candidate_sha256": skill_hash, "complete": True,
                    "recovered_official_postprocessing": True,
                    "agent_exception_trials": sum(bool(r.get("exception_info")) for r in prior_trials),
                    "target_model_role": "Harbor LocalPi / DeepSeek V4 Flash", "thinking": "off",
                }, indent=2) + "\n", encoding="utf-8")
                return self._convert_records(records, Path(out_dir), split)

        stamp = time.strftime("%Y%m%d-%H%M%S")
        job_root = self.jobs_root / candidate_id / split / f"{stamp}-{time.time_ns() % 1000000000:09d}"
        job_root.mkdir(parents=True, exist_ok=False)
        request_manifest = {
            "candidate_id": candidate_id,
            "split": split,
            "candidate_sha256": skill_hash,
            "expected_case_count": len(expected),
            "concurrent": self.concurrent,
            "max_retries": self.max_retries if self.supports_max_retries else None,
            "retry_policy": "explicit-cli" if self.supports_max_retries else "Harbor/Kit default",
            "state": "running",
        }
        (job_root / "run_request.json").write_text(
            json.dumps(request_manifest, indent=2) + "\n", encoding="utf-8"
        )
        command = [
            str(self.run_script),
            "--bench",
            self._bench_name(split),
            "--reasoning",
            "off",
            "--concurrent",
            str(self.concurrent),
            "--model-id",
            str(_target_model_id()),
            "--base-url",
            proxy_credentials("target").base_url,
            "--jobs-dir",
            str(job_root),
        ]
        if self.supports_max_retries:
            command.extend(["--max-retries", str(self.max_retries)])
        if skill_dir:
            command.extend(["--skills-dir", str(Path(skill_dir).resolve())])
        env = os.environ.copy()
        target_proxy = proxy_credentials("target")
        if env.get("TRACE2SKILL_DIRECT_LOCAL") != "1":
            env["TRACE2SKILL_TARGET_PROXY_TOKEN"] = target_proxy.token
        started = time.time()
        with (job_root / "runner.log").open("w", encoding="utf-8") as log:
            proc = subprocess.run(
                command,
                cwd=self.kit_root.parent,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                # Keep the orchestrator alive through full splits and Harbor's
                # summary/export phase. Transient failed trials are retried by
                # Harbor itself via --max-retries; do not kill/restart a live
                # job on a quiet period because valid tasks can take a while.
                timeout=24 * 60 * 60,
                check=False,
            )
        run_dirs = sorted(p for p in job_root.iterdir() if p.is_dir())
        if not run_dirs:
            raise RuntimeError(f"Harbor run failed (exit={proc.returncode}); see {job_root / 'runner.log'}")
        result_dir = run_dirs[-1]
        summary_path = result_dir / "summary.json"
        if not summary_path.is_file():
            completed = []
            for result_path in result_dir.glob("*/result.json"):
                try:
                    completed.append(json.loads(result_path.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    continue
            if (
                len(completed) == len(expected)
                and {normalize_case_id(r.get("task_name")) for r in completed} == expected
                and all(r.get("finished_at") and ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward") is not None for r in completed)
            ):
                return self.run_split(split, items, skill_dir=skill_dir, out_dir=out_dir, candidate_id=candidate_id)
            raise RuntimeError(f"Harbor did not write its official summary: {summary_path}")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        trial_results = []
        for result_path in result_dir.glob("*/result.json"):
            try:
                trial_results.append(json.loads(result_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        actual_ids = {normalize_case_id(row.get("task_name")) for row in trial_results if row.get("task_name") is not None}
        all_scored = (
            len(trial_results) == len(expected)
            and actual_ids == expected
            and all(row.get("finished_at") for row in trial_results)
            and all(
                ((row.get("verifier_result") or {}).get("rewards") or {}).get("reward") is not None
                for row in trial_results
            )
            and int(summary.get("n_trials", -1)) == len(expected)
        )
        # Harbor can score a trial that ended with an agent exception as zero.
        # Preserve that official result and expose the exception in the ATIF
        # export rather than silently discarding the whole split.
        recovered_model_error_summary = (
            proc.returncode == 4
            and all_scored
            and int(summary.get("errors", 0)) > 0
        )
        if not all_scored or (proc.returncode != 0 and not recovered_model_error_summary):
            raise RuntimeError(f"Harbor run incomplete or failed (exit={proc.returncode}); see {job_root / 'runner.log'}")
        trace_path = result_dir / "traces.jsonl"
        if not trace_path.is_file():
            exporter = self.kit_root / "results/export_traces.py"
            export_python = self.kit_root / "workspace/.venv/bin/python"
            exported = subprocess.run(
                [str(export_python), str(exporter), "--job", str(result_dir), "--output", str(trace_path)],
                cwd=self.kit_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            if exported.returncode != 0 or not trace_path.is_file():
                raise RuntimeError(f"Harbor ATIF export failed (exit={exported.returncode}) for {result_dir}")
        (job_root / "run_manifest.json").write_text(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "split": split,
                    "job_dir": str(result_dir),
                    "trace_file": str(trace_path),
                    "skill_dir": str(skill_dir) if skill_dir else None,
                    "candidate_sha256": skill_hash,
                    "complete": True,
                    "harbor_cli_exit_code": proc.returncode,
                    "recovered_model_error_summary": recovered_model_error_summary,
                    "official_summary_errors": int(summary.get("errors", 0)),
                    "agent_exception_trials": sum(bool(row.get("exception_info")) for row in trial_results),
                    "model_error_events": int(summary.get("model_error_events", 0)),
                    "concurrent": self.concurrent,
                    "max_retries": self.max_retries if self.supports_max_retries else None,
                    "retry_policy": "explicit-cli" if self.supports_max_retries else "Harbor/Kit default",
                    "target_model_role": "Harbor LocalPi / DeepSeek V4 Flash",
                    "thinking": "off",
                    "wall_time_seconds": round(time.time() - started, 2),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for record in records:
            record["case_id"] = normalize_case_id(record.get("case_id"))
        if {str(r.get("case_id")) for r in records} != expected or len(records) != len(expected):
            raise RuntimeError("Harbor ATIF export does not match the full official split")
        return self._convert_records(records, Path(out_dir), split)

    def _convert_records(self, records: list[dict], out: Path, split: str) -> list[dict]:
        out.mkdir(parents=True, exist_ok=True)
        manifest = json.loads((self.kit_root / "benchmark" / "splits" / split / "items.json").read_text(encoding="utf-8"))
        task_types = {str(row["id"]): str(row.get("task_type", "")) for row in manifest}
        results = [
            convert_record(
                record, out,
                task_type=task_types.get(str(record.get("case_id", "")), ""),
                benchmark=self.benchmark,
            )
            for record in records
        ]
        (out / "rollouts.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return results


def _target_model_id() -> str:
    """Load the non-secret target model ID from the public Round 1 config."""
    import yaml

    module_path = Path(__file__).resolve()
    candidates = [
        module_path.parents[3] / "configs/harbor_pi/default.yaml",
        module_path.parents[4] / "configs/harbor_pi/default.yaml",
    ]
    config_path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if config_path is None:
        raise FileNotFoundError("configs/harbor_pi/default.yaml not found next to SkillOpt package")
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return str(cfg["model"]["target_openai_compatible_model"])
