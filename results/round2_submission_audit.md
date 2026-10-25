# Round 2 submission and reproduction audit — 2026-10-26

Source of requirements: [official Trace2Skill rules, ALFWorld v2](https://bs3-hb1.corp.kuaishou.com/infra-wanqing-llm-gateway/evolve-inputs/skill-creator-match/RULES.html?x-bs-client-force=true&v=20261019-alfworld-v2#alfworld), read on 2026-10-26. The official Round 2 split is 39 Train / 18 Val / 134 Test. Round 2 begins from a blank Skill; Round 1's Skill is not inherited. Final submission is a single reproducible self-improvement scheme with `src/`, `skills/`, `README.md`, `DESIGN.md`, and `results/`.

| Requirement | Current delivery | Assessment |
| --- | --- | --- |
| Standard Skill and optional resources | `skills/alfworld-strategy/SKILL.md` and `scripts/safe_send.py`, with frozen hashes in `results/alfworld-v2-confirmed-best.json` | Present |
| Source, setup, design | Vendored SkillOpt core, Harbor adapter, `pyproject.toml`, README and DESIGN | Present |
| Official Train → Val workflow | `scripts/run_alfworld_evolution.py` uses official splits, Kimi optimizer, fixed Pi, DeepSeek Thinking OFF, and official scoring | Runnable on a configured clean Kit, but its stochastic search does not deterministically generate H005 |
| H005 official Val evidence | Two complete paired full-Val comparisons: H005 18/18 and 17/18; no Skill 16/18 and 16/18. Complete second-pair ATIF and official summaries are bundled. | Present; this is Val evidence, not Test evidence |
| Skill-generation token accounting | H001–H003 Kimi search: 38,751 tokens; deterministic H004/H005 package construction: 0 additional generation tokens. See H005 delivery report. | Summary present; full H001–H003 generation artifacts and source Train traces are not included in the compact public bundle |
| Independent 134-case Test | An October 25 attempt was stopped when its candidate `--skills-dir` was found to register both the Round 1 spreadsheet Skill and Round 2 ALFWorld Skill. No no-Skill Test control had run. Its partial data is excluded. The corrected script stages only ALFWorld Skill and a new full paired run has started. | **Not yet complete; no valid Test improvement claim** |
| Clean-checkout replay of H005 candidate-selection history | Historical `alfworld_hypothesis_*` commands require a frozen `diagnostic_plan.json` and C001/C002 Train rollout files under the local campaign directory. They are not in this compact submission. | **Not one-command reproducible**; the frozen Skill and Val evidence are inspectable |
| New Bench reuse | Core Reflect/Aggregate/Select/Update/gate is shared; each new official Kit still needs benchmark split/task mapping and domain Skill metadata. | Partially reusable; not a zero-configuration hidden-Bench runner |

## Reproduction boundary

The competition Kit, Docker runtime, authorized DeepSeek/Kimi endpoints and credentials are external inputs by rule. A clean checkout can install the submitted Python package and run `pytest -q tests`; it can execute `scripts/run_alfworld_evolution.py` against a separately installed official ALFWorld Kit after setting `HARBOR_KIT_ROOT` and runtime model credentials. This reproduces the **algorithmic search procedure**, not the exact stochastic H005 discovery path or the historical 18/18 and 17/18 outcomes.

For the **frozen H005 package**, a reviewer can stage only `skills/alfworld-strategy/` in a Skill parent directory and use the Kit's `./run.sh --bench alfworld-val --skills-dir <parent>` for an independent full Val run. The package's official paired evidence is under `results/alfworld-v2-h005-delivery/`. Model stochasticity means a fresh score need not equal either historical run. The corrected `scripts/alfworld_final_test.py` stages only that Round 2 Skill; it checks both file hashes and all 134 official Test IDs before comparing H005 with no Skill.

## Outstanding work before claiming full formal reproducibility

1. Include a portable, sanitized H005 Train diagnostic plan and its source/protected Train case evidence, then make its diagnostic and gate commands runnable from a clean checkout without C001/C002 private workspace artifacts.
2. Unify the deterministic, Train-derived executable-helper hypothesis into the generic candidate-generation interface, or explicitly submit it as a predeclared candidate family selected by a reproducible Train gate. The current generic SkillOpt run does not automatically invent H005.
3. Complete the isolated official 134-case H005/no-Skill Test, inspect execution errors and paired results, and publish final ATIF, official summaries and model/optimizer token accounting. The aborted mixed-Skill attempt must not be used as evidence.
4. Replace date-specific output roots in the campaign follow-up scripts with a configurable run root and document a clean-start versus resume path. Keep each independent run immutable.

**Conclusion:** The repository meets the requested directory shape and contains a standard Round 2 Best Skill plus credible official Val evidence. It is a useful reviewable stage submission. It does **not yet** meet a strict interpretation of “the organizer can reproduce the exact Round 2 self-evolution from an empty checkout with one command,” nor can it claim a final Test gain.
