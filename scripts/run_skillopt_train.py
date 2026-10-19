#!/usr/bin/env python3
"""Launch SkillOpt's native multi-epoch trainer with private model settings."""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
SUBMISSION = HERE.parents[1]
sys.path.insert(0, str(SUBMISSION / "src"))

from skillopt.envs.harbor_pi.security import assert_real_run_ready, proxy_credentials  # noqa: E402

assert_real_run_ready()
optimizer_proxy = proxy_credentials("optimizer")
target_proxy = proxy_credentials("target")
os.environ["OPTIMIZER_OPENAI_COMPATIBLE_API_KEY"] = optimizer_proxy.token
os.environ["TARGET_OPENAI_COMPATIBLE_API_KEY"] = target_proxy.token
os.environ["OPTIMIZER_OPENAI_COMPATIBLE_BASE_URL"] = optimizer_proxy.base_url
os.environ["TARGET_OPENAI_COMPATIBLE_BASE_URL"] = target_proxy.base_url

config = SUBMISSION / "configs/harbor_pi/default.yaml"
train_script = SUBMISSION / "src/scripts/train.py"
os.chdir(SUBMISSION)
sys.argv = [str(train_script), "--config", str(config), *sys.argv[1:]]
from scripts.train import main  # noqa: E402

main()
