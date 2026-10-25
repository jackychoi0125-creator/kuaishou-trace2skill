#!/usr/bin/env python3
"""Freeze H006 from Train-observed batched-action failures; no model calls."""
from __future__ import annotations

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

BODY = """# Closed-loop public action guard for ALFWorld

First call `bridge.sh start <episode-id>`. Before the first action, ask the
bundled helper for the current observation and its action token:

```bash
python3 /root/.agents/skills/alfworld-strategy/scripts/safe_send.py <episode-id> observe
```

Choose **one** command from that result's `admissible_commands`. Send it with
the exact `next_action_token` shown in the same result:

```bash
python3 /root/.agents/skills/alfworld-strategy/scripts/safe_send.py <episode-id> '<one admissible action>' '<next_action_token>'
```

Read the returned observation and token **before choosing another action**.
Do not launch several actions in one tool batch: the token is single-use, so
preplanned actions with an old token will be declined without spending the
official action budget. If the result contains `skill_guard`, no action was
sent; choose again from its current observation and admissible commands.

The helper uses only public `bridge.sh status/send` and the official public
action transcript. It rejects non-admissible commands and a third identical
`go to` in a row. Stop when `won` or `done` is true. The helper does not edit
the official transcript, the fixed Pi Agent, or the scorer.
"""


def main() -> None:
    root = RUN_ROOT / "campaign/hypotheses/H006"
    if (root / "candidate_manifest.json").exists():
        raise FileExistsError("H006 already frozen")
    content = f"---\nname: alfworld-strategy\ndescription: {DESCRIPTION}\n---\n\n{BODY}"
    skill = package_skill(content, root / "candidate/skills")
    source = SUBMISSION / "src/trace2skill/alfworld_turn_guard.py"
    scripts = skill.parent / "scripts"
    scripts.mkdir()
    helper = scripts / "safe_send.py"
    shutil.copyfile(source, helper)
    helper.chmod(0o755)
    manifest = {
        "candidate_id": "H006",
        "source_case_ids": ["train:0029", "train:0030"],
        "protected_case_ids": ["train:0013", "train:0017", "train:0021", "train:0028", "train:0038"],
        "mechanism": "single-use public observation token prevents several preplanned actions from one Pi response",
        "skill_path": str(skill), "skill_sha256": hashlib.sha256(skill.read_bytes()).hexdigest(),
        "helper_path": str(helper), "helper_sha256": hashlib.sha256(helper.read_bytes()).hexdigest(),
        "optimizer_model_calls": 0, "optimizer_generation_tokens": 0,
        "metadata_variant": "same_original_description_as_H004",
        "train_only": True, "val_executed": False, "test_executed": False,
    }
    plan = json.loads((RUN_ROOT / "campaign/hypotheses/H004/diagnostic_plan.json").read_text(encoding="utf-8"))
    plan.update({
        "candidate_id": "H006",
        "train_gate": "At least 12/14 official Train passes, no terminal model/execution errors, at most one stable-success regression, and at least five helper-adoption cases. Val remains conditional and H004 is the frozen Train comparator for mechanism analysis.",
        "candidate_type": "Standard Skill plus a single-use observation-token helper; no fixed Pi, bridge or scorer modification.",
    })
    (root / "candidate_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "diagnostic_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"candidate_id": "H006", "skill_sha256": manifest["skill_sha256"],
                      "helper_sha256": manifest["helper_sha256"]}))


if __name__ == "__main__":
    main()
