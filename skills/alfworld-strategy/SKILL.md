---
name: alfworld-strategy
description: Use for ALFWorld household tasks that execute bridge.sh actions. Read this Skill before the first action to use its public action guard script for admissibility, repeated navigation and the 50-action budget.
---

# Public action guard for ALFWorld

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
