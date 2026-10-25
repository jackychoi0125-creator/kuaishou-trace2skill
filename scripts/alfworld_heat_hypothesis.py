#!/usr/bin/env python3
"""Propose a narrow heat-task Skill from saved Train trajectories with Kimi."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

SUBMISSION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUBMISSION / "src"))
sys.path.insert(0, str(SUBMISSION / "scripts"))

from alfworld_hypothesis_candidate import DESCRIPTION, _public_action_evidence  # noqa: E402
from run_alfworld_evolution import RUN_ROOT, load_local_config, runtime_env, yaml_models  # noqa: E402
from skillopt.envs.harbor_pi.skill_packager import package_skill  # noqa: E402
from skillopt.model.openai_compatible_backend import (  # noqa: E402
    chat_optimizer, configure_openai_compatible, get_token_summary, reset_token_tracker,
)
from skillopt.utils import extract_json  # noqa: E402


def main() -> None:
    out = RUN_ROOT / "campaign/hypotheses/H002"
    if (out / "candidate_manifest.json").exists():
        raise FileExistsError("H002 already exists")
    out.mkdir(parents=True, exist_ok=True)
    evidence = {
        "repeat_failure": {"case_id": "train:0029", "runs": [
            _public_action_evidence("train:0029", job) for job in ("C001-best-train", "C002-best-train")
        ]},
        "successful_heat_guards": [
            {"case_id": cid, "runs": [_public_action_evidence(cid, job) for job in ("C001-best-train", "C002-best-train")]}
            for cid in ("train:0027", "train:0028", "train:0031", "train:0032", "train:0033")
        ],
        "candidate_regression_example": _public_action_evidence("train:0028", "A001-failure-mechanics"),
    }
    (out / "train_evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    key, base_url, ids = load_local_config()
    models = yaml_models()
    if any(ids.get(k) != v for k,v in models.items()):
        raise RuntimeError("active model IDs do not match local configuration")
    os.environ.update(runtime_env(key, base_url))
    configure_openai_compatible(
        optimizer_base_url=base_url, optimizer_api_key=key, optimizer_model=models["kimi-k2.6"],
        optimizer_max_tokens=90000, optimizer_completion_token_field="max_completion_tokens",
        optimizer_thinking="enabled", optimizer_reasoning_effort="high",
        optimizer_temperature=0.2, optimizer_timeout_seconds=600,
    )
    system = (
        "You are SkillOpt's curator. Use only the supplied official Train action traces and rewards. "
        "Create ONE falsifiable, narrowly applicable heating-task skill hypothesis. The fixed Pi agent "
        "cannot be modified. Do not copy routes, object numbers, case IDs or answers into the Skill. "
        "Protect the already successful heating cases. The official task already says to choose one "
        "admissible action and stop when done; do not merely repeat those instructions. Invalid/repeated "
        "actions spend the 50-action budget. Return JSON only."
    )
    user = (
        "TRAIN evidence:\n" + json.dumps(evidence, ensure_ascii=False) +
        "\nPropose a conditional rule about a concrete failure mechanism that differentiates the "
        "failed heating traces from successful direct transformations. Require observable current "
        "location, inventory and admissible-action preconditions; specify when NOT to apply it and "
        "when to stop. Do not assert that microwave opening is universally wrong. Return JSON keys "
        "hypothesis, source_case_ids, protected_case_ids, applicability, non_applicability, "
        "expected_observable_behavior, rejection_signal, skill_body. skill_body is Markdown under "
        "250 words with no benchmark case ID or numeric object route."
    )
    reset_token_tracker()
    response, usage = chat_optimizer(system=system, user=user, max_completion_tokens=90000,
                                     retries=2, stage="alfworld_heat_hypothesis", timeout=600)
    parsed = extract_json(response)
    if not isinstance(parsed, dict):
        raise RuntimeError("Kimi did not return JSON")
    body = str(parsed.get("skill_body") or "").strip()
    if not body or len(body) > 3000 or len(body.split()) > 300 or re.search(r"\b(?:train|val|test):\d{4}\b", body, re.I):
        raise RuntimeError("H002 failed deterministic Skill content validation")
    content = f"---\nname: alfworld-strategy\ndescription: {DESCRIPTION}\n---\n\n{body}\n"
    skill = package_skill(content, out / "candidate/skills")
    manifest = {
        "candidate_id": "H002", "source_case_ids": ["train:0029", "train:0028"],
        "protected_case_ids": ["train:0027", "train:0028", "train:0031", "train:0032", "train:0033"],
        "skill_path": str(skill), "skill_sha256": hashlib.sha256(skill.read_bytes()).hexdigest(),
        "optimizer_model": models["kimi-k2.6"], "optimizer_thinking": "on",
        "max_completion_tokens": 90000, "optimizer_usage": get_token_summary(),
        "raw_response_usage": usage, "train_only": True, "val_executed": False, "test_executed": False,
    }
    (out / "hypothesis.json").write_text(json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "candidate_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"candidate_id": "H002", "sha256": manifest["skill_sha256"],
                      "generation_tokens": (manifest["optimizer_usage"].get("_total") or {}).get("total_tokens")}))


if __name__ == "__main__":
    main()
