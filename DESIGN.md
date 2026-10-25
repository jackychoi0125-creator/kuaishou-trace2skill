# Design: evidence-constrained Skill evolution

## Competition boundary

Harbor Kit creates the task Trial, its pinned Pi Agent executes with an optional standard Skill, and Harbor's official evaluator supplies the score. SkillOpt's target-model chat backend is never used as a replacement benchmark agent. DeepSeek V4 Flash is the Harbor Pi target with Thinking OFF; Kimi K2.6 is the optimizer with Thinking ON and a verified 90,000-token completion ceiling. Train traces enter optimization, Val is used only for paired acceptance, and Test remains outside the development loop.

## Evolution algorithm

The Harbor adapter loads official split manifests, invokes the official Kit, exports ATIF records, and maps official per-case rewards to optimizer rollouts. The trace converter retains ordered user, assistant, tool-call, tool-result, error, and final-answer events. It stores raw traces for audit and creates a deterministic compact view for model context, retaining task IDs, key evidence, errors, terminal output, and omission hashes for clipped bulk output.

Contrastive Reflect groups Train examples by task family inferred from task text, then analyzes both failed and successful trajectories. Generated edits retain source case IDs, success counterexamples, applicability and non-applicability conditions, expected effects, and regression risk. This protects against treating every single failure as a universal rule, although heuristic grouping and LLM inference can still be wrong.

SkillOpt's native Aggregate and Select remain in the path. A configurable risk filter checks provenance, conditions, counterexamples, duplicate/conflicting content, and unbounded absolute language. At most one semantic edit is applied to a candidate. The native Update mechanism edits the current Best-derived Skill; the packager validates standard frontmatter and emits the Harbor/Pi directory structure.

The campaign initializes Best from the legitimate current Skill and its official Val result, then records paired per-case scores keyed by Skill hash. Each candidate receives a Train regression screen before full Val. A strict official Accuracy improvement is required for provisional acceptance; regressions, fixed cases, delivery failures, runtime, and token use are diagnostics. Rejection leaves Best intact, stores the rejected edit in the buffer, and continues within candidate and token budgets. Checkpoints make each phase resumable and prevent repeating completed model stages when their outputs were persisted.

The optimizer reserves the configured completion ceiling against the token budget before calls. This is intentionally conservative. Provider usage records separate input, output, reasoning, and cache subsets without double-counting. If persisted model output lacks its original usage checkpoint, the manifest marks total optimizer usage incomplete rather than inventing a number. Harbor target tokens are reported independently from Skill Generation Tokens.

## Current experiment evidence

`results/C001-20261019-delivery/` contains C001 contrastive Reflect/Aggregate/Select/Update artifacts, Train screen, paired Val decision, and selected official Harbor summaries and ATIF trace. The initial current-Best official Val was 30/40. C001 scored 63/80 on Train against the same-round Best's 62/80, with 11 fixed and 10 regressed cases. Its complete concurrency-one Val was 31/40, with 7 fixed, 6 regressed, and net +1; the configured strict gate accepted it provisionally. It is exported as the package Best. The one-case gain needs repeat confirmation before claiming a stable improvement.

The first Reflect process persisted patch output but exited before its in-memory usage checkpoint was written. C001 therefore correctly records optimizer usage as incomplete. Its currently visible 1,622 tokens are only a lower bound from resumed ranking/selection operations. No claim of total generation-token efficiency should use that partial figure. C001 Val used 2,086,242 input tokens (including 1,584,896 cached subset), 429,494 output tokens, and no reported reasoning tokens. It recorded zero Harbor/model errors, retries, exceptions, or actual HTTP 429 responses.

## Reliability and scope

Harbor runs are serialized at concurrency one to reduce endpoint RPM/TPM contention observed in earlier concurrent experiments. The wrapper timeout is longer than a full sequential Train run so post-run official summary and trace export can finish; this does not change Pi, task, scorer, or per-trial evaluation limits. Retry behavior remains the Kit's configured behavior and is recorded per run.

The evolution, provenance, risk selection, checkpoint, token, and gate logic is benchmark-agnostic. The Harbor rollout now also supports the official Round 2 ALFWorld v2 Kit through benchmark configuration and its official split/task mapping. A later benchmark still needs an adapter for its official data and trace/task mapping; it does not require rewriting the optimizer. Domain Skill metadata and generated Skills are scoped so spreadsheet practices do not leak into ALFWorld or other benchmarks.

## Round 2: executable, opt-in action Skill

ALFWorld Train traces showed that Pi sometimes emits many Bridge actions in one model response, exhausting the official 50-action budget before it can use fresh observations. A natural-language H001 rule was insufficient: it passed one source case but failed its frozen Train screen after a 36-send batch. H002/H003 were rejected before Harbor when source action/observation evidence did not support the generated claims. The Kimi hypothesis search consumed 38,751 generation tokens and is retained for audit.

H004/H005 test a narrower Train-derived operational hypothesis using the competition's standard optional Skill `scripts/` directory. The script reads only official public Bridge state and the public action transcript, checks admissibility, serializes its own invocations, and declines a third identical navigation command. It never edits Pi, the Bridge, the private game, or the official scorer. Pi must choose to read and call it. H005 changes only H004's standard YAML description to make the relevant Bridge workflow discoverable; Skill body and helper bytes are identical. This follows [ReAct's](https://arxiv.org/abs/2210.03629) action/observation principle and the motivation for executable skills in [HASP](https://arxiv.org/abs/2605.17734), while respecting the frozen Pi interface. [HDSO](https://arxiv.org/abs/2606.22330) and [GRASP](https://arxiv.org/abs/2605.29668) support the predeclared Train gate and paired regression check; published results are not treated as our benchmark evidence.

H005 passed its frozen Train subset (13/14). Official full Val scored 18/18 versus no Skill 16/18, then a complete independent repeat scored 17/18 versus no Skill 16/18, with no terminal model/Harbor errors. Its confirmed export is `skills/alfworld-strategy/`. In the repeat all 18 trials read and invoked the Skill; official actions fell from 451 to 250. The paired fixed cases were `val:0002` and `val:0016`; `val:0013` regressed. At that regression, Pi trace step 17 still emitted 55 helper calls in one response; 24 were blocked as non-admissible, while the remainder exhausted all 50 official actions. Thus the helper can improve action efficiency but cannot guarantee one fresh observation per model decision.

The host-side pass-through used for the complete repeat keeps the upstream credential out of the Pi container, forwards unchanged OpenAI-compatible target requests, and permits bounded 429 retry. Both candidate and no Skill used the same pass-through and concurrency one. It observed zero upstream 429s in the final repeat; one other upstream error/transport event did not cause a terminal trial error. The score gain therefore does not depend on a successful 429 retry. `results/alfworld-v2-h005-delivery/` contains both 18-case ATIF-v1.8 repeat traces, official summaries, paired evidence and hashes. Test has not been run.

H006 is a separate candidate frozen from Train before H005's Val, with a single-use observation token intended to decline stale batched actions. It remains untested in official Harbor and is not the exported Best. Its next gate is the same frozen Train regression screen, followed by a full Val comparison only if qualified.

## Limits

One candidate passing Train screening does not imply generalization. Val is small and model execution is stochastic, so small gains require repeat confirmation before Best is considered final. Prior R1 and P1 experiments showed that additional instructions can regress strong native behavior and that Skill loading alone does not establish causal benefit. The system therefore prioritizes paired official scores and retains per-case evidence instead of treating readability, Skill trigger rate, or optimizer confidence as acceptance criteria.
