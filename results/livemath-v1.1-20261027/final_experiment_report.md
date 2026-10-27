# LiveMath v1.1: SkillOpt + Harbor experiment

## Scope and evidence boundary

Official Kit: `pi-harbor-kit-livemath-v1.1-20261025`, Harbor 0.23.0, Pi 0.85.1. The target is DeepSeek V4 Flash with Thinking OFF; the optimizer is Kimi K2.6 with Thinking ON and `max_completion_tokens=90000`. The official `final-response` profile, fixed option permutation, seed 0, timeout 1800 seconds, concurrency 4 and unchanged scorer were used for all reported comparisons. Train has 35 tasks, Val 17, Test 125. Kimi used only Train traces and Train labels. No Val/Test reference answer or proof sketch was used for Skill generation.

The official Kit writes an independent comparison for each completed run. The Kit's own `compare_runs.py` accepted the no-Skill and C002 Val pair as equivalent evaluation conditions and reported the same score delta as the SkillOpt gate. Local raw ATIF and job artifacts are retained in this result directory and the separate Kit workspace; they are not part of the public Skill.

## Measured results and frozen confirmation

| Run | Split | Correct | Accuracy | Input tokens including cache | Output tokens | Wall seconds | Official task errors |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| No Skill R0 | Train | 4/35 | 11.43% | 386,783 | 207,584 | 1,508 | 0 |
| No Skill R0 | Val | 3/17 | 17.65% | 151,010 | 70,579 | 538 | 0 |
| C002 Skill | Train | 5/35 | 14.29% | 453,067 | 208,563 | 1,126 | 0 |
| C002 Skill | Val | 6/17 | 35.29% | 185,051 | 120,745 | 670 | 0 |
| Fresh no Skill | Val confirmation | 4/17 | 23.53% | 100,013 | 51,554 | See official job | 0 |
| Frozen C002 Skill | Val confirmation | 7/17 | 41.18% | 211,664 | 81,852 | See official job | 0 |

The C002 Train pair has three fixed and two regressed cases. The Val pair has three fixed and zero regressed cases (`202601:31`, `202601:46`, `202602:15`). Full Skill body load is observable in 34/35 candidate Train traces and 16/17 candidate Val traces. Two Val fixes loaded the body; one (`202601:46`) did not. On Train, the two loaded fixes were offset by two loaded regressions. This makes the first Val gain promising but does not prove causal or stable Skill benefit. In the 17-case Val pair, the exact paired two-sided sign/McNemar test for three discordances is 0.25; repeat confirmation is warranted.

In the two fixed-and-loaded Val cases, the final responses visibly discuss stronger theorem statements; one also explicitly contrasts specific options. This is consistent with the Skill rule but cannot distinguish Skill influence from the target model's native reasoning. The unloaded fixed case gave a very short boxed final response and provides no full-body Skill attribution. The paired rows, including load step, tool calls and token changes, are in `c002_paired_val_analysis.csv`.

The independent frozen confirmation ran the same 17 Val IDs sequentially under the same endpoint and official scorer: no Skill passed 4/17, then unchanged C002 passed 7/17. Its paired result has three fixes (`202511:17`, `202602:15`, `202602:8`) and zero regressions, with zero official errors or output-limit finishes. The complete C002 Skill body was observed in all 17 candidate tool results. The two pairs each show a +3/17 aggregate Skill advantage, but only `202602:15` is fixed in both pairs. The no-Skill repeat fixed `202601:31` on its own relative to the first no-Skill run; that case was originally credited as a C002 fix. The result supports a promising aggregate gain, not deterministic case-level causality or an 80% projection. The second pair used 111,651 more Target input and 30,298 more Target output tokens with Skill; cached tokens are included in input.

The candidate Val run produced one invalid final-answer format (`202512:36`), despite a normal `stop` finish and no Harbor task error. The first no-Skill Val had no invalid answer. Both runs mostly failed by selecting a scored wrong option. No model output limit was reached in the baseline or C002 Train/Val analyses. These are outcome diagnostics only and did not enter further Train Patch generation.

## Evolution and generation cost

C001's first streaming optimizer pass consumed 169,313 reported generation tokens but returned no parseable candidate. Source review found that the LiveMath prompt had replaced the native SkillOpt JSON Patch instructions, a plausible cause of the parse failures; C001's response bodies were not saved, so the exact model-output defect cannot be reconstructed. The native schema was restored ahead of the LiveMath guidance, and later optimizer responses plus per-batch checkpoints are auditable. Earlier nonstreaming connection failures returned no server usage; any potential billable tokens for those failed requests are unknown and excluded from reported totals.

C002 used the fixed native Reflect, Aggregate, Select and Update path. Nine Reflect batches produced nine raw edits. The risk filter rejected three for missing success counterexamples; Aggregate merged six eligible edits; native Select chose one semantic edit, `p-5e34073ca75c`, with failed Train sources `202511:14`, `202511:16`, `202511:20`, `202511:26` and success counterexample `202512:16`. The edit teaches comparison of theorem strength and the “stronger result” meta-option. The Skill SHA256 is `df969f97395b369529e8a1274d9048e2eedfb263f94a424b9cde62cde77a1657`.

| C002 optimizer stage | Input | Output including reasoning | Reasoning subset | Cache subset of input | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Reflect | 104,522 | 55,476 | 49,047 | 3,840 | 159,998 |
| Aggregate | 5,129 | 10,524 | 7,321 | 0 | 15,653 |
| Select | 1,997 | 5,724 | 5,475 | 0 | 7,721 |
| **Total C002** | **111,648** | **71,724** | **61,843** | **3,840** | **183,372** |

Reasoning and cached tokens are subsets, not extra additions. The first two attempts together consumed 352,685 reported generation tokens; only C002 produced a candidate. The accepted C002 Val score improved by three cases at 183,372 candidate-generation tokens, while C001's 169,313 yielded no usable edit. C002's selected success counterexample `202512:16` regressed in the candidate Train rollout, showing that the pre-update risk estimate was overconfident. The Train screen allowed the net +1/35 result under its 0.05 tolerance. The first gate accepted C002 provisionally at 6/17.

The C002 `decision.json` mistakenly recorded Target usage as zero because its job lookup omitted the Kit's nested `official-jobs` directory. `c002_target_usage_correction.json` records the unchanged official summary: 185,051 input, 120,745 output, 85,248 cached subset, 305,796 total Target tokens. The source lookup has been corrected for future decisions. The original decision is preserved for audit.

The first attempt to resume C003 exposed a separate implementation error: `--initial-no-skill` was reapplied after C002 had been accepted, resetting Best state to R0. That attempt used the no-Skill 4/35 Train baseline as its reflection and comparison input while appending to C002's text. It was stopped after only one candidate Train trial completed and **before any C003 Val**. Its artifacts live under `campaign/aborted/20261028-C003-invalid-best-resume/`; its 11 metered Kimi calls consumed **236,435** generation tokens and remain in the total cost. Best was restored from the unmodified C002 Val decision and SHA256. The resume initializer now keeps an accepted Best, with a regression test. A second adapter fix recognizes the official Kit's null whole-trial-retry setting as zero, allowing the corrected C003 to reuse C002's exact clean 35-case Train rollout instead of launching a redundant Best Train job. The corrected C003 inputs have **5/35** passing cases and the C002 Skill hash. The invalid attempt is excluded from all gate decisions.

The corrected C003 performed eight failed-example and two successful-example Reflect calls from that 5/35 Train rollout. It selected one additional edit, `p-545b1470c78d`, based on failed Train IDs `202602:31`, `202602:41`, `202602:45`, `202602:46` and successful counterexample `202512:21`. The edit warns against choosing an unsupported claim merely because it includes a precise author, exponent, qualifier or quantitative estimate. Its packaged Skill SHA256 is `4bd6efb1ca4ba7b5fa4536c0876caa9377222a4b6b8983d96cd9aab5f3baa0d3`; it adds 554 characters to C002. Corrected C003 generation consumed **270,060** reported tokens, reconstructed from 12 per-response audits. One 52,526-token Reflect response contained explanatory prose plus a valid final Patch JSON; the upstream parser returned no Patch because the prose contained extra brace fragments. A strict unique-JSON fallback now recovers that shape for future runs, and the recovered Patch is saved for diagnosis but was **not** inserted into the active C003 candidate.

C003 completed its 35-case Train screen at **5/35**, with one fix (`202512:32`) and one regression (`202512:21`). The regression was the selected Patch's own cited successful counterexample; the old net-only screen let this balanced result proceed. On official Val, C003 scored **6/17**, tied with C002: fixes `202512:36`, `202602:8` were offset by regressions `202601:46`, `202602:15`. The strict Accuracy Gate **rejected** C003 and kept C002 Best. All C003 Train and Val trials completed without official task errors, empty responses or output truncation; full Skill body load appeared in 34/35 Train and 17/17 Val. Its full diagnosis is in `c003_diagnostic.md`. A subsequent code change now blocks a candidate if its selected Patch regresses a cited successful Train counterexample, even when net Train score is unchanged. This guard was added **after** C003's completed decision; the recorded C003 Val result remains unchanged. The full offline test suite now passes 46 tests.

Including C001, C002, the aborted invalid attempt, and corrected C003, observed skill-generation usage is **859,180 tokens** before C003 Train/Val evaluation. This is above the prior Round 1 R1's 427,433 tokens; the campaign cannot be described as globally more token-efficient. The 1,000,000-token budget includes aborted calls rather than resetting on resume.

## Train-only failure analysis and industry context

All 31 no-Skill Train failures were valid but incorrect labels, not missing deliveries or tool exceptions. The model overselected one label and underselected a theorem-strength meta-option in the prepared Train questions; these are Train diagnostics, not instructions to hardcode a label or always choose the meta-option. The current Skill attempts to check the strongest listed true statement against potentially stronger theorems. It still caused Train regressions and increased Val Target output by 50,166 tokens, so more reasoning is not itself a quality guarantee.

The [LiveMathematicianBench paper](https://arxiv.org/abs/2604.01754) describes recent-paper theorem questions with plausible logical distractors and reports a 43.5% best-model score in its standard setting. [Step verification](https://arxiv.org/abs/2305.20050) and [self-consistency](https://arxiv.org/abs/2203.11171) motivate checking hypotheses, quantifiers and competing theorem strengths, but those papers do not establish that a static Skill can raise this fixed non-thinking target above 80%. The Kit supplies no proof sketch or paper to the Agent, and its model-evaluation network allowlist is restricted to the configured endpoint.

## Reproduction and remaining gates

From the `submission` directory after installing the official Kit and activating the project environment:

```bash
export HARBOR_KIT_ROOT=/path/to/pi-harbor-kit-livemath-v1.1
python scripts/run_livemath_evolution.py --resume --max-candidates 3 --token-budget 1000000 --minibatch-size 4
python scripts/confirm_livemath_val.py --campaign results/livemath-v1.1-20261027/campaign --out results/livemath-v1.1-20261027/confirmation-1
python scripts/export_livemath_best.py --campaign results/livemath-v1.1-20261027/campaign --confirmation results/livemath-v1.1-20261027/confirmation-1/paired_result.json
python scripts/run_livemath_final_test.py --campaign results/livemath-v1.1-20261027/campaign --confirmation results/livemath-v1.1-20261027/confirmation-1/paired_result.json --out results/livemath-v1.1-20261027/final-test
```

The direct local endpoint and credential are configured externally; do not put a key on the command line or in a submitted report. The confirmation script runs one fresh full no-Skill Val and one frozen-Best Val sequentially. The Test script refuses a changed Skill hash and is only appropriate after Best and the comparison protocol are frozen. Neither command feeds Val/Test errors into new Skill generation.

**Current status:** C003 was rejected at 6/17, and the unchanged C002 Best passed a frozen independent Val confirmation at 7/17 versus 4/17 no Skill. Its SHA256 is `df969f97395b369529e8a1274d9048e2eedfb263f94a424b9cde62cde77a1657`, exported to `skills/livemath-strategy/SKILL.md`. One frozen held-out Test run is in progress. The >80% Test goal has **not** been demonstrated.
