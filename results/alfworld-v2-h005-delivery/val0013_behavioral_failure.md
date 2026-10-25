# `val:0013`: why a loaded Skill can still fail

This is a post-evaluation diagnosis only. It does not change H005 or create a new candidate from Val data.

| Run | Official result | Official actions | Helper calls | Most helper calls in one Pi model step | Model error events | Output tokens |
|---|---:|---:|---:|---:|---:|---:|
| H005 first full Val | pass | 11 | 12 | 1 | 0 | 1,801 |
| H005 earlier confirmation retry | fail | 37 | 46 | 6 | 4 terminal HTTP 429 events | 18,450 |
| H005 `proxy1` paired confirmation | fail | 50 | 74 | 55 | 0 | 56,377 |

In `proxy1`, the Pi trace confirms a full Skill body read at step 2 and 74 calls to the bundled script. The script declined 24 non-admissible commands, but Pi trace **step 17** alone emitted 55 helper calls. The 50 commands that remained admissible exhausted the official environment budget. This is a directly observed failure of **action/observation interleaving** even after Skill discovery and use; it is not a Pi registration failure or an HTTP 429 failure in this run. The official binary `won` reward is 0, with no Harbor exception. The long model response makes a substantial contribution to the trial's latency and target output cost.

H006's single-use observation token was frozen from the earlier **Train** multi-call failure before this Val run. If H006 later passes its predeclared Train screen, a full Val test could check whether it blocks this class of batch calls. This report does not use `val:0013` as a Patch source and does not claim H006 works.
