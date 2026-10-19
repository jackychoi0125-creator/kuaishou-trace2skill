"""Harbor Kit execution wrapper; all grades and traces come from Harbor."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from .security import proxy_credentials
from .trace_converter import convert_record


class HarborKitRollout:
    def __init__(self, kit_root: str | Path, jobs_root: str | Path) -> None:
        self.kit_root = Path(kit_root).resolve()
        self.jobs_root = Path(jobs_root).resolve()
        self.run_script = self.kit_root / "run.sh"
        if not self.run_script.is_file():
            raise FileNotFoundError(self.run_script)

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
            skill_file = Path(skill_dir) / "spreadsheet-workflow" / "SKILL.md"
            if not skill_file.is_file():
                skill_file = Path(skill_dir) / "SKILL.md"
            if not skill_file.is_file():
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
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
            if (
                manifest.get("complete") is True
                and manifest.get("candidate_sha256") == skill_hash
                and job_dir.joinpath("summary.json").is_file()
                and {str(r.get("case_id")) for r in records} == expected
                and len(records) == len(expected)
            ):
                return self._convert_records(records, Path(out_dir))

        stamp = time.strftime("%Y%m%d-%H%M%S")
        job_root = self.jobs_root / candidate_id / split / f"{stamp}-{time.time_ns() % 1000000000:09d}"
        job_root.mkdir(parents=True, exist_ok=False)
        command = [
            str(self.run_script),
            "--bench",
            f"spreadsheetbench-{split}",
            "--reasoning",
            "off",
            "--concurrent",
            "1",
            "--model-id",
            str(_target_model_id()),
            "--base-url",
            proxy_credentials("target").base_url,
            "--jobs-dir",
            str(job_root),
        ]
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
                # Full official splits can exceed three hours at concurrency 1.
                # Harbor may have finished every trial while its post-run
                # summary/export steps are still pending; keep the orchestration
                # timeout above the observed full-Train runtime so recovery
                # does not require rerunning a completed expensive split.
                timeout=8 * 60 * 60,
                check=False,
            )
        run_dirs = sorted(p for p in job_root.iterdir() if p.is_dir())
        if proc.returncode != 0 or not run_dirs:
            raise RuntimeError(f"Harbor run failed (exit={proc.returncode}); see {job_root / 'runner.log'}")
        result_dir = run_dirs[-1]
        trace_path = result_dir / "traces.jsonl"
        if not trace_path.is_file():
            raise RuntimeError(f"Harbor did not export ATIF traces: {trace_path}")
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
        if {str(r.get("case_id")) for r in records} != expected or len(records) != len(expected):
            raise RuntimeError("Harbor ATIF export does not match the full official split")
        return self._convert_records(records, Path(out_dir))
    @staticmethod
    def _convert_records(records: list[dict], out: Path) -> list[dict]:
        out.mkdir(parents=True, exist_ok=True)
        results = [convert_record(record, out) for record in records]
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
