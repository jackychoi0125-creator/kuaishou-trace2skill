# C001 Harbor result export

This directory contains the C001 SkillOpt optimizer artifacts and the official Harbor run summaries/traces used for the paired gate. Per-trial container logs, copied workbooks, and generated answer scripts are omitted from this GitHub export; full originals remain in the local experiment root referenced by the live campaign manifest. `best_train` and `candidate_train` are the same-round full Train guard; `best_val` is the exact-current-Best official Val initialization; `candidate_val` is the complete 40-case official Harbor Val run.

C001 was provisionally accepted by the strict accuracy gate: 31/40 vs 30/40 (7 fixed, 6 regressed, net +1). It has not been repeat-confirmed. Optimizer generation usage is incomplete because the first Reflect process failed to checkpoint its response usage; the recorded 1,622 tokens are a lower bound.
