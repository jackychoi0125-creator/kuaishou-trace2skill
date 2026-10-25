# H005 official ALFWorld Val evidence

This compact bundle contains the **complete 18-case independent paired repeat**: raw Harbor ATIF-v1.8 traces for H005 and no Skill, each official `summary.json`, a case-paired behavior/score analysis, the confirmation decision, transport counts, and Skill/trace hashes. Both trace files contain 18 unique case IDs and no upstream credential. The first full Val's official summaries and per-case decision records are included separately; its much larger raw run remains in the local experiment workspace.

The confirmed H005 Skill is at `../../skills/alfworld-strategy/SKILL.md`, with its supporting `scripts/safe_send.py`. `industry_method_review.md` records the primary research used to choose the experiment, and `val0013_behavioral_failure.md` records the main observed regression. The result is **Val** evidence, not a held-out Test result. `val:0013` is a documented regression despite H005's net accuracy gain.

`train_diagnostic_plan.json` is the frozen 14-case official Train selection; `train_guard_reference.json` retains its two no-Skill per-case regression guards; `train_diagnostic_result.json` contains H005's official 13/14 Train score and gate decision with local machine paths removed. These are audit snapshots, not a replacement for the full raw Train ATIF or a clean-checkout replay of the earlier candidate-generation process.
