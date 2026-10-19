# Vendored SkillOpt core

The `src/skillopt/` package and `src/scripts/` entry points vendor Microsoft's SkillOpt implementation and retain its native Reflect, Aggregate, Select, Update, model, and engine code. This snapshot also includes the competition integration changes already present in this project: contrastive reflection support, risk-aware selection, Harbor/Pi adapter, role-specific model configuration and security handling. Trace2Skill campaign extensions are maintained in `src/trace2skill/`.

Upstream: https://github.com/microsoft/SkillOpt
Upstream base commit: 343db229dbd5ddaf9df6b1d5540d8bcdb2604d5c
Vendored project snapshot: 0e7af944b1a58e788a323dccc7aaad13e49e967f
License: MIT (see `LICENSE`).
