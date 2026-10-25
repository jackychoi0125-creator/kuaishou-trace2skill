#!/usr/bin/env python3
"""Package a standard Skill with an opt-in public action guard.

The candidate is based on observed Train batch-call failures. No Val/Test
trace, answer, route, or model generation call is used by this builder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

SUBMISSION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUBMISSION / "src"))
sys.path.insert(0, str(SUBMISSION / "scripts"))

from alfworld_hypothesis_candidate import DESCRIPTION  # noqa: E402
from run_alfworld_evolution import RUN_ROOT  # noqa: E402
from skillopt.envs.harbor_pi.skill_packager import package_skill  # noqa: E402

GUARD_DESCRIPTION = (
    "Use for ALFWorld household tasks that execute bridge.sh actions. Read this Skill before "
    "the first action to use its public action guard script for admissibility, repeated "
    "navigation and the 50-action budget."
)

BODY = """# Public action guard for ALFWorld

Use `bridge.sh start <episode-id>` to obtain the initial observation. For each
subsequent environment action, call the bundled guard **once**, then inspect
its JSON response before choosing the next action:

```bash
python3 /root/.agents/skills/alfworld-strategy/scripts/safe_send.py <episode-id> '<one admissible action>'
```

The guard calls the official public `bridge.sh status`, confirms that the
proposed action is currently admissible, and then calls the official
`bridge.sh send`. Parallel invocations of this guard are serialized and
rechecked after the previous action. It also declines a third identical
`go to` command in a row. A `skill_guard` field means **no action was sent**;
read the returned observation and admissible commands, then choose a different
action. Do not retry the same declined action without new evidence.

Stop when `won` or `done` is true. The official bridge writes the only
authoritative action transcript; the guard never edits it.
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-id", choices=("H004", "H005"), default="H004")
    args = parser.parse_args()
    candidate_id = args.candidate_id
    root = RUN_ROOT / "campaign/hypotheses" / candidate_id
    if (root / "candidate_manifest.json").exists():
        raise FileExistsError(f"{candidate_id} already exists")
    description = DESCRIPTION if candidate_id == "H004" else GUARD_DESCRIPTION
    content = f"---\nname: alfworld-strategy\ndescription: {description}\n---\n\n{BODY}"
    skill = package_skill(content, root / "candidate/skills")
    source = SUBMISSION / "src/trace2skill/alfworld_safe_send.py"
    scripts = skill.parent / "scripts"
    scripts.mkdir()
    helper = scripts / "safe_send.py"
    shutil.copyfile(source, helper)
    helper.chmod(0o755)
    manifest = {
        "candidate_id": candidate_id, "source_case_ids": ["train:0021", "train:0029", "train:0038"],
        "protected_case_ids": ["train:0015", "train:0017", "train:0028", "train:0038"],
        "mechanism": "standard Skill script validates public status and serializes opt-in bridge sends",
        "skill_path": str(skill), "skill_sha256": hashlib.sha256(skill.read_bytes()).hexdigest(),
        "helper_path": str(helper), "helper_sha256": hashlib.sha256(helper.read_bytes()).hexdigest(),
        "optimizer_model_calls": 0, "optimizer_generation_tokens": 0,
        "metadata_variant": "original_description" if candidate_id == "H004" else "guard_trigger_description",
        "train_only": True, "val_executed": False, "test_executed": False,
    }
    (root / "candidate_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"candidate_id": candidate_id, "skill_sha256": manifest["skill_sha256"],
                      "helper_sha256": manifest["helper_sha256"]}))


if __name__ == "__main__":
    main()
