# ALFWorld skill hypotheses: evidence and external methods

## Observed failure mechanism in the frozen Pi + Harbor runs

The clean no-skill Train repeats scored 34/39 and 31/39; seven task outcomes changed between runs. The official no-skill Val score is 16/18. Thus a single task flip is within the observed scale of run-to-run variation, and a candidate must clear a frozen Train screen before the one full Val gate.

For `train:0021`, one no-skill trajectory ended with fourteen consecutive `go to cabinet 3` actions; H001 used at most two consecutive identical navigation actions and passed. This is correlated behavioral evidence, not proof of a Skill effect.

For `train:0029`, H001 read the complete `SKILL.md`, then one Pi model response emitted 36 `bridge.sh send` calls, many repeating `go to shelf 1`. A rule that checks the *previous two observations* cannot interrupt a preplanned multi-call response. The fixed agent's task instruction already says to choose one admissible action per turn, and the previously tested A001 Skill made that reminder explicit; neither reliably constrained parallel tool calls. This is a concrete limitation of text-only control through the standard Skill interface.

## Primary research and applicability

- [HDSO](https://arxiv.org/abs/2606.22330) proposes narrowly scoped, falsifiable skills with paired screening; its ALFWorld results motivate H001's single conditional rule and frozen Train gate. HDSO's executor can operationalize skills, while this competition fixes Pi, so its reported gain does not transfer directly.
- [GRASP](https://arxiv.org/abs/2605.29668) uses bounded skill selection and held-out paired regression checks. Its validation principle supports rejecting H002 before expensive Harbor evaluation when its causal claim lacks Train evidence.
- [ReAct](https://arxiv.org/abs/2210.03629) shows the value of interleaving reasoning and actions for long-horizon environments. Here, a large batch of tool calls in one Pi response prevents that interleaving even when the Skill asks for it.
- [ExpeL](https://arxiv.org/abs/2308.10144) distills task experiences and retrieves relevant examples. A future Train-only variant could use observation-grounded successful/failed pairs, but it requires a new candidate and real Harbor screening; no benefit is assumed.
- [HASP](https://arxiv.org/abs/2605.17734) formalizes executable skill functions that intervene at failure-prone states. Its motivation matches the observed weakness of passive ALFWorld text rules. The competition's fixed Pi loop does not expose HASP's automatic intervention hook, so H004/H005 implement an optional standard Skill script instead. Its effect requires an observable Pi invocation; this is an inference from the method, not a claim that our agent has HASP's intervention mechanism.

## Changes made for this campaign

`alfworld_hypothesis_candidate.py` now includes a compact observation extractor that matches every tool result by `source_call_id`, retains the goal and selected failure observations, and preserves the original official Train actions. The unit test checks reversed result order within a multi-call step. H002 demonstrates why this matters: its generated narrative claimed that the agent placed a mug into a microwave, but neither source Train action sequence contains such a placement. H002 was rejected without Harbor evaluation and its generation cost remains recorded.

H004 tests the narrow action-level idea in a form allowed by the standard Skill directory: an optional script inside the Skill calls only the public `bridge.sh status/send`, serializes its own invocations, checks admissibility against current state, and declines a third identical navigation command. It neither alters fixed Pi nor the official Bridge/scorer. This is an **experiment**, not a proven improvement; if Pi does not call the helper, there is no mechanism of effect. Its Train plan requires observable helper invocation in at least 5/14 fixed cases before any Val run.

The next metadata-only variant H005 preserved the exact H004 Skill body and helper bytes but made the description point to the public Bridge action workflow. It passed the frozen Train screen (13/14) and initially scored 18/18 on official Val against historical no-Skill 16/18. Because the no-Skill Train runs varied, that single Val result remained provisional. Two subsequent confirmation attempts encountered terminal HTTP 429 errors. A complete, error-free paired repeat through the same host-side pass-through scored H005 17/18 versus no Skill 16/18, so the gate confirmed H005. The pass-through recorded no upstream 429 responses during the final pair; its score gain was associated with observed Skill use and changed action trajectories, with the remaining `val:0013` batching regression documented separately.
