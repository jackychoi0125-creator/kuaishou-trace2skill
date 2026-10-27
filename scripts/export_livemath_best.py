#!/usr/bin/env python3
"""Export only a Val-confirmed LiveMath Best into the standard submission Skill path."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SUBMISSION = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--confirmation", type=Path, required=True)
    parser.add_argument("--out", type=Path,
                        default=SUBMISSION / "skills/livemath-strategy/SKILL.md")
    args = parser.parse_args()
    campaign, out = args.campaign.resolve(), args.out.resolve()
    state = json.loads((campaign / "best/best.json").read_text(encoding="utf-8"))
    source = campaign / "best/skills/livemath-strategy/SKILL.md"
    body = source.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    if digest != state.get("skill_sha256"):
        raise RuntimeError("Best Skill SHA256 mismatch")
    confirmation = json.loads(args.confirmation.resolve().read_text(encoding="utf-8"))
    if (confirmation.get("frozen_skill_sha256") != digest
            or int(confirmation.get("case_count", -1)) != 17
            or int(confirmation.get("best_skill_passed", -1)) <= int(confirmation.get("no_skill_passed", -1))):
        raise RuntimeError("cannot export without an improving paired Val confirmation")
    if out.is_file() and out.read_bytes() != body:
        raise FileExistsError(f"refusing to overwrite a different exported Skill: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    manifest = {
        "candidate_id": state.get("candidate_id"), "skill_sha256": digest,
        "source": str(source), "exported_skill": str(out),
        "confirmation": str(args.confirmation.resolve()),
        "no_skill_passed": confirmation["no_skill_passed"],
        "best_skill_passed": confirmation["best_skill_passed"],
    }
    (out.parent / "export_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                                     encoding="utf-8")
    print(json.dumps({"candidate_id": manifest["candidate_id"], "skill_sha256": digest,
                      "exported_skill": str(out)}))


if __name__ == "__main__":
    main()
