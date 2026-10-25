# Trace2Skill: Harbor + SkillOpt

This is the competition submission package for evolving standard Agent Skills from Harbor Train traces and evaluating them with Harbor's fixed Pi Agent and official scorer. The target task runner remains Harbor; SkillOpt's target-model chat path is not used to solve benchmark tasks.

## Package contents

- `src/skillopt/`: vendored native SkillOpt core, including its Reflect, Aggregate, Select, Update, model backends, optimizer, evaluation, and engine modules.
- `src/scripts/`: native SkillOpt training/evaluation entry points.
- `src/skillopt/envs/harbor_pi/`: Harbor rollout, ATIF conversion, task loading, Skill packaging, and model/security adapters.
- `src/trace2skill/`: contrastive reflection extensions, patch risk screening, bounded campaign orchestration, and recovery helpers.
- `configs/harbor_pi/default.yaml`: role-specific model and Harbor configuration.
- `skills/spreadsheet-workflow/SKILL.md`: Round 1 SpreadsheetBench Best Skill.
- `skills/alfworld-strategy/SKILL.md`: repeat-confirmed Round 2 ALFWorld Best Skill, with its standard supporting script.
- `scripts/trace2skill.py`: command line for model checks, baseline/rollout, trace conversion, evolution, search, evaluation, export, token reports, and comparisons.
- `results/C001-20261019-delivery/`: the curated C001 optimizer artifacts and official Harbor Train/Val evidence included in this repository snapshot.
- `results/alfworld-v2-h005-delivery/`: official 18-case paired ALFWorld Val traces, summaries, scores, model/transport cost and hashes; `results/alfworld-v2-h005-delivery.md` explains the confirmed result and limits.

## Reproduction boundary

This directory contains the optimizer and Harbor adapter source needed to reproduce the algorithm; it does not depend on the parent SkillOpt checkout. Its Python dependencies are declared in `pyproject.toml`. The official Harbor Kit v3.3-layout2, benchmark dataset/manifests, and authorized runtime endpoint credentials remain external competition inputs and are not copied into this package. Set `HARBOR_KIT_ROOT` to the official Kit path and `TRACE2SKILL_WORKSPACE` to the directory containing it when the default sibling layout is unavailable. Credentials are runtime-provided and are not included. The C001 score and traces in `results/C001-20261019-delivery/` are included for audit without live model access.

The vendored native SkillOpt code is based on Microsoft's commit `343db229dbd5ddaf9df6b1d5540d8bcdb2604d5c`, with the project integration snapshot identified in `UPSTREAM_SKILLOPT.md`; see that file and `LICENSE` for provenance. Trace2Skill-specific changes are in `src/trace2skill/` and the Harbor integration under `src/skillopt/envs/harbor_pi/`.

## Reproduction

From this directory, install the submitted package and inspect the CLI:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python scripts/trace2skill.py --help
```

The bounded campaign command reuses the existing official no-thinking Train trace for the initial Reflect pass, then performs a fresh current-Best Train rollout for regression screening. Only candidates passing the configured Train screen proceed to the full official Val gate:

```bash
export HARBOR_KIT_ROOT=/path/to/spreadsheetbench-harbor-kit-v3.3-layout2
python scripts/trace2skill.py search \
  --run-root results/<unique-run-id> \
  --initial-train-trace "$HARBOR_KIT_ROOT/workspace/traces/train-baseline-nothink.jsonl" \
  --max-candidates 2 --token-budget 900000
```

Do not reuse a completed run root for an independent experiment. `--resume` is for continuing its own checkpointed campaign. Harbor jobs use `--concurrent 1` in the current profile to avoid shared-endpoint rate-limit interference. Val is evaluation-only and never enters Reflect. Test is intentionally excluded from development search.

Useful separate operations are `model-check`, `baseline`, `convert`, `evolve`, `evaluate`, `export-best`, `tokens`, `compare`, and `pipeline`; consult `--help` for exact arguments. The current adapter validates official split membership and refuses arbitrary/partial benchmark selections.

## Models and accounting

The Round 1 profile assigns DeepSeek V4 Flash with Thinking OFF to the Harbor Pi target and Kimi K2.6 with Thinking ON to SkillOpt. The Kimi request uses the verified `max_completion_tokens` field with a configured ceiling of 90,000; this is a limit, not a requested output size. Model IDs and non-secret request settings are recorded in the experiment report. Credentials are supplied at runtime and are not stored in this package or experiment manifests.

Optimizer generation usage is reported by stage separately from Harbor target usage. Reasoning and cached tokens are reported as subsets when the provider reports them; they are not added twice to completion/input totals. An interrupted process may leave a documented usage gap if a provider response was persisted before its in-memory usage checkpoint; such totals are marked incomplete rather than presented as exact.

## C001 delivery snapshot

The C001 audit bundle is `results/C001-20261019-delivery/`. The initial official Val baseline was 30/40 (0.75). C001 completed the full 40-case Harbor Val at 31/40 (0.775), with 7 fixed, 6 regressed, and net +1 case; the strict Accuracy gate provisionally accepted it. The Skill in `skills/spreadsheet-workflow/SKILL.md` is C001, SHA256 `5f43c165452e948a16d112e813395a1a6e2b1e5df315c4cc92f7476937eebe5b`. The gain is small and has not had repeat confirmation, so it should be treated as provisional. The bundle includes the SkillOpt patch provenance, Train screen, paired Val decision, official summaries, and ATIF Val trace.

C001's Train screen was 63/80 versus the same-round prior Best's 62/80, with 11 fixed and 10 regressed cases. C001 Val had 0 Harbor errors, model-error trials, task exceptions, retries, or actual HTTP 429 responses. C001 target usage was 2,086,242 input tokens (including 1,584,896 cached-token subset), 429,494 output tokens, 0 reported reasoning tokens, 2,515,736 total, and 8,255 seconds wall time.

C001 optimizer usage is marked incomplete because the Reflect response usage was not checkpointed by the process that first persisted its output. The visible 1,622 tokens cover only resumed ranking/selection work and are a lower bound, not the candidate's total generation cost. Do not use its `score_gain_per_1m_generation_tokens` field as a valid efficiency comparison. C002 work is outside this C001 delivery snapshot.

## Tests

From this directory:

```bash
source .venv/bin/activate
pytest -q tests
```

The full offline SkillOpt suite has passed in the SkillOpt checkout. Harbor integration checks and live model/Harbor smoke evidence are recorded under `results/upgrade-20261018-live-b/`. Offline tests do not establish benchmark score improvement; only the official paired Val gate does.

## New benchmark support

The evolution and gate logic does not depend on SpreadsheetBench's fixed sample counts or case IDs. A new benchmark requires a compatible Harbor adapter for its official split manifests and trace/task mapping, plus benchmark-specific Skill metadata. Keep Reflect, Aggregate, risk screening, native Select/Update, checkpoints, token accounting, and acceptance logic unchanged where the Kit contract permits.

## Round 2 ALFWorld v2

The assembled official Kit is expected at `../benchmarks/alfworld-v2-kit` relative to this package. The Round 2 profile is `configs/round2_alfworld.yaml`; its split sizes are 39 Train, 18 Val, and 134 held-out Test. The benchmark-specific starter is `src/skillopt/envs/alfworld/skills/blank.md`. The Pi target, official binary `won` scorer, and 50-action limit remain those of the Kit.

From this submitted package root, point to the official Kit and provide a private endpoint credential through the environment or the Kit's private `kit.env`. `TRACE2SKILL_WORKSPACE` is only needed when using the existing local `model.txt` fallback:

```bash
source .venv/bin/activate
export HARBOR_KIT_ROOT=/path/to/alfworld-v2-kit
export TRACE2SKILL_LOCAL_BASE_URL=https://your-authorized-endpoint-base
export TRACE2SKILL_LOCAL_API_KEY=your-authorized-runtime-token
python -u scripts/run_alfworld_evolution.py
```

The runner resumes the completed official Train baseline, runs the full Val baseline, and starts a bounded one-edit SkillOpt candidate search. Candidate generation reads Train ATIF only. The optimizer excludes trials with an agent exception or no model response from Reflect while retaining their official scores and raw traces. A baseline with those errors cannot serve as the paired Train regression guard; a fresh full no-Skill Train rollout is run if a real candidate is produced. Val comparisons with execution or zero-response errors are marked inconclusive rather than accepted. Results and checkpoints are under `results/alfworld-v2-20261020-evolution/`. The current iteration does not run Test; a frozen best candidate must be selected before a single final Test evaluation.

### Observation-grounded hypothesis and public action guard

The October 25 follow-up scripts under `scripts/alfworld_hypothesis_*.py` implement a bounded Train-first experiment with official Pi/Harbor evaluation. They preserve every candidate and its SHA256 under `results/alfworld-v2-20261020-evolution/campaign/hypotheses/`. H001 used the configured Kimi optimizer with Thinking ON, was rejected by its frozen Train gate, and never reached Val. H002/H003 were rejected before Harbor after checking their causal claims against Train observations and previously rejected edits. Their model Token usage is still recorded.

H004 tests a standard Skill with `SKILL.md` and a supporting `scripts/safe_send.py`. The script calls only the Kit's public `bridge.sh status/send` and reads its public action transcript. It checks current admissibility and serializes its own invocations; the fixed Pi and official Bridge/scorer are unchanged. It has no effect unless Pi actually invokes it. H005 is a frozen metadata-only variant with the same body and script. The Train plan requires at least 12/14 official passes, no disqualifying execution/model errors, at most one regression among stable no-Skill successes, and observable helper calls in at least five cases. Only then may one full Val run occur.

From this package root, after the authorized model and Kit runtime configuration is available:

```bash
source .venv/bin/activate
PYTHONPATH=src pytest -q tests
python scripts/alfworld_guarded_skill_candidate.py --candidate-id H004
python scripts/alfworld_hypothesis_diagnostic.py --candidate-id H004
python scripts/alfworld_hypothesis_analysis.py --candidate-id H004
python scripts/alfworld_hypothesis_val.py --candidate-id H004
python scripts/alfworld_hypothesis_confirm.py --candidate-id H004
```

The candidate builder refuses to overwrite an existing manifest; on this workspace, H004/H005 are already built, so resume at the diagnostic or analysis command. The Val command refuses a failed Train gate. The confirmation command refuses a candidate that did not first beat the no-Skill Val baseline and never edits the Skill. If the repeated candidate and no-Skill runs do not both show an improvement, the result remains inconclusive or rejected. H005 has now met that confirmation gate (18/18 and 17/18, versus 16/18 and 16/18 no Skill); it is the exported Round 2 Best. Test remains unrun.

H006 is a separate, frozen Train-derived hypothesis for the observed case where Pi issues many actions in one model response. Its optional helper requires the unpredictable token from the previous public observation before sending one official action. Stale batched actions are declined and never reach the official Bridge. It preserves the original H004 Skill metadata and uses the same frozen 14-case Train subset. To build or assess it after other Harbor jobs finish:

```bash
python scripts/alfworld_turn_guard_candidate.py  # only if H006 is not already built
python scripts/alfworld_hypothesis_diagnostic.py --candidate-id H006
python scripts/alfworld_hypothesis_analysis.py --candidate-id H006
```

Only a candidate passing its recorded Train gate may run `alfworld_hypothesis_val.py --candidate-id H006`. H006 is experimental and must not be exported as Best based on local tests or loading rate alone.

After a candidate receives `CONFIRMED_ACCEPT` from the balanced official Val repeat, export the exact frozen Skill and supporting script to the competition's standard directory with:

```bash
python scripts/alfworld_export_confirmed.py --candidate-id H005
```

The export command checks the full Val gate, repeat confirmation and both SHA256 values. It refuses to overwrite a different exported Skill, archives the prior Round 2 `best.json`, and updates Best to the confirmed candidate. It does not run Test or make model calls. Without confirmation, the Round 2 Best remains the no-Skill R0 state and this command fails closed. If a confirmation attempt suffers terminal HTTP 429 errors, record it as incomplete, then use `--attempt-label retry1` for a new full candidate plus no-Skill paired repeat; this option requires the persisted infrastructure-error record and never replays selected cases.

For the October 25 H005 confirmation, the endpoint repeatedly returned HTTP 429 even with Harbor concurrency 1. A bounded host-side pass-through can retry the identical target request with `Retry-After` or exponential backoff. It keeps the upstream credential outside the Pi container and gives the container a one-run token; model ID, Thinking OFF, task set, scorer, and Pi behavior remain unchanged. On a clean campaign, run one complete paired confirmation with:

```bash
source .venv/bin/activate
python scripts/alfworld_hypothesis_confirm.py --candidate-id H005 --retry-proxy
```

If a previous attempt was documented as incomplete due to HTTP 429, use a new `--attempt-label` such as `proxy1` to get independent Harbor directories. Each proxy attempt writes aggregate counts to `confirmation_proxy_metrics-<label>.json`; it never records model request bodies or credentials. This is a transport retry, not a way to replay selected failed tasks. Check `confirmation.json` for a complete candidate/no-Skill paired result before exporting the Skill.

After a complete confirmation, `python scripts/alfworld_hypothesis_confirm_analysis.py --candidate-id H005` writes a case-paired, offline report of official rewards, Skill reads, helper calls, action counts and target output tokens. It makes no model calls and refuses partial trial sets.
