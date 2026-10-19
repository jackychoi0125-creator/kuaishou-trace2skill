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

The evolution, provenance, risk selection, checkpoint, token, and gate logic is benchmark-agnostic. The current rollout and split adapter is specific to the Round 1 Harbor/SpreadsheetBench Kit layout. A later benchmark needs an adapter for its official data and trace/task mapping; it does not require rewriting the optimizer. Domain Skill metadata and generated Skills should be scoped so spreadsheet practices do not leak into unrelated benchmarks.

## Limits

One candidate passing Train screening does not imply generalization. Val is small and model execution is stochastic, so small gains require repeat confirmation before Best is considered final. Prior R1 and P1 experiments showed that additional instructions can regress strong native behavior and that Skill loading alone does not establish causal benefit. The system therefore prioritizes paired official scores and retains per-case evidence instead of treating readability, Skill trigger rate, or optimizer confidence as acceptance criteria.
