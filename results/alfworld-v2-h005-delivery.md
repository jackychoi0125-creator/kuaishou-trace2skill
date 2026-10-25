# ALFWorld Round 2 H005 delivery (2026-10-25)

## Decision and official scores

H005 is a standard Skill package containing `skills/alfworld-strategy/SKILL.md` and `scripts/safe_send.py`. It was built from Train failure observations and passed its frozen 14-case Train screen at **13/14** (the two no-Skill screens were 11/14 and 10/14). The official Harbor/Pi full Val results are:

| Run | No Skill | H005 | Candidate minus baseline | Error trials |
|---|---:|---:|---:|---:|
| First full Val | 16/18 | 18/18 | +2 | 0 / 0 |
| Complete independent repeat | 16/18 | 17/18 | +1 | 0 / 0 |

The repeat's paired transitions are **fixed `val:0002`, `val:0016`; regressed `val:0013`**. `confirmation.json` records `CONFIRMED_ACCEPT`; the export command moved the frozen candidate to the standard submission Skill directory and updated Round 2 Best. The Skill SHA256 is `aabcef463d4e8b65759d801d8317d0188f43dc5e2c72934de83bcf76a72857f6`; the helper SHA256 is in the candidate manifest and confirmed Best manifest. The two-run H005 mean is **35/36 = 97.22%**, versus **32/36 = 88.89%** for no Skill. These repeated Val results do **not** establish a held-out Test gain; Test was not run.

## Observed mechanism and remaining failure

The repeat read the full H005 body and invoked its helper in **18/18** cases. H005 executed **250** official actions against **451** for the paired no-Skill run. `val:0016` is especially informative: no Skill issued up to 29 direct Bridge sends in one Pi model step, exhausted 50 actions and failed; H005 loaded the Skill, called the helper 17 times, succeeded in 14 actions. On `val:0004`, both passed, but H005 used 6 actions and 1,373 output tokens versus 46 actions and 14,466 output tokens without Skill. These are observed paired behaviors, not a controlled proof that every score change was caused by the Skill.

H005 did not solve all batching. At `val:0013` it loaded the body at Pi trace step 2, but step 17 emitted **55 helper calls in one model response**. The helper rejected 24 non-admissible proposals; the remaining admissible actions still exhausted the official 50-action budget. It failed without model or Harbor errors and consumed 56,377 target output tokens. Its first full Val had passed this case in 11 actions with one helper call per model step. This stochastic switch is direct evidence that text instructions plus an opt-in helper do not reliably enforce action/observation interleaving.

## Model, transport and cost

All Harbor runs used the frozen Pi Agent, official ALFWorld Bridge and binary `won` scorer, DeepSeek V4 Flash with Thinking OFF, the same 18 Val IDs, and concurrency 1. H005 changed only the standard Skill package relative to no Skill. The repeat used the same host-side pass-through for both groups. It forwarded unchanged model requests, kept the upstream credential outside the Pi container, and allowed bounded HTTP 429 retries. Its metrics recorded **553** requests, **0** upstream HTTP 429 responses, **0** retries, **0** exhausted retries, and **1** other upstream error response/transport event; no trial ended in a model error. Therefore this repeat's score gain cannot be attributed to successful 429 retry.

| Repeat metric | No Skill | H005 |
|---|---:|---:|
| Official passed | 16/18 | 17/18 |
| Target input tokens, including cache | 2,912,044 | 1,845,742 |
| Cached subset of input | 2,559,744 | 1,485,056 |
| Target output tokens | 137,542 | 170,231 |
| Official actions | 451 | 250 |
| Wall seconds | 3,031 | 3,216 |

The cache field is a subset of input and is not added again. H005's deterministic package construction used **0 new Kimi generation tokens**. The preceding H001–H003 hypothesis search did use Kimi K2.6 Thinking ON: 12,289 + 8,708 + 17,754 = **38,751** generation tokens; reasoning tokens are subsets of completion tokens. H004/H005's new generation cost is zero. These optimizer tokens and the DeepSeek Harbor evaluation tokens are separate accounts.

## Why this method and what to do next

The original natural-language patch could not prevent Pi from sending many actions in one model response. [ReAct](https://arxiv.org/abs/2210.03629) motivates interleaving an action with its observation; [HASP](https://arxiv.org/abs/2605.17734) explains why executable, state-sensitive functions may be stronger than passive text advice. The frozen competition Pi has no automatic skill-intervention hook, so H005 uses only an optional standard Skill script calling the official public Bridge. [HDSO](https://arxiv.org/abs/2606.22330) and [GRASP](https://arxiv.org/abs/2605.29668) motivate the frozen Train screen and repeated paired Val gate; their published gains are not used as evidence for this candidate.

The next targeted candidate is H006's single-use observation token. It was frozen from Train evidence **before** this Val analysis and has not been run in Harbor. It should first pass the same predeclared Train screen, with explicit checks that stale same-response calls are declined, then face at most one full Val gate. Do not use `val:0013` as a Patch source. Do not claim H006 or held-out Test improvement until official results exist.

## Audit files and reproduction

- `results/alfworld-v2-h005-delivery/`: compact upload bundle with both complete repeat ATIF-v1.8 traces (18 unique case IDs each), official summaries, paired scores, transport counts and hashes. Its files were scanned for the configured upstream credential and Bearer-token patterns before delivery; neither was found.
- `alfworld-v2-20261020-evolution/campaign/hypotheses/H005/confirmation.json`: official paired decision and IDs.
- `alfworld-v2-20261020-evolution/campaign/hypotheses/H005/confirmation_behavior-proxy1.json`: all 18 paired rewards, reads, helper calls, actions and output tokens.
- `alfworld-v2-20261020-evolution/campaign/hypotheses/H005/confirmation_proxy_metrics-proxy1.json`: transport counts.
- `alfworld-v2-20261020-evolution/campaign/hypotheses/H005/val0013_behavioral_failure.md`: the key regression with Pi trace step.
- `alfworld-v2-confirmed-best.json`: portable Skill path and checksums.
- `scripts/alfworld_hypothesis_confirm.py` and `scripts/alfworld_hypothesis_confirm_analysis.py`: repeat and offline paired analysis commands; `scripts/alfworld_export_confirmed.py` only exports after confirmation.

The independent submission package passed **26 offline tests** with `PYTHONPATH=src pytest -q tests`. The official Pi/Harbor run and paired Val evidence above are the live validation. The source SkillOpt core remains vendored inside `src/skillopt/` for reproducibility, and the official Kit remains an external competition input.
