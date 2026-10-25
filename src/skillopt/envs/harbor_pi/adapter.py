"""SkillOpt adapter whose target rollout is the Harbor Kit fixed Pi Agent."""

from __future__ import annotations

from pathlib import Path

from skillopt.datasets.base import BatchSpec
from skillopt.envs.base import EnvAdapter

from .dataloader import HarborSplitDataLoader
from .rollout import HarborKitRollout
from .skill_packager import package_skill


class HarborPiAdapter(EnvAdapter):
    def __init__(self, split_dir: str = "", kit_root: str = "", jobs_root: str = "", seed: int = 42, **kwargs) -> None:
        self.split_dir = str(Path(split_dir).resolve())
        self.kit_root = str(Path(kit_root).resolve())
        self.jobs_root = str(Path(jobs_root or "outputs/harbor_pi/jobs").resolve())
        if not split_dir or not kit_root:
            raise ValueError("HarborPiAdapter requires official split_dir and kit_root")
        self.dataloader = HarborSplitDataLoader(self.split_dir, seed=seed)
        self.runner = HarborKitRollout(self.kit_root, self.jobs_root)

    def setup(self, cfg: dict) -> None:
        super().setup(cfg)
        self.dataloader.setup(cfg)

    def get_dataloader(self):
        return self.dataloader

    def build_env_from_batch(self, batch: BatchSpec, **kwargs):
        return list(batch.payload or [])

    def build_train_env(self, batch_size: int, seed: int, **kwargs):
        return self.build_env_from_batch(self.dataloader.build_train_batch(batch_size, seed))

    def build_eval_env(self, env_num: int, split: str, seed: int, **kwargs):
        return self.build_env_from_batch(self.dataloader.build_eval_batch(env_num, split, seed))

    def rollout(self, env_manager, skill_content: str, out_dir: str, **kwargs) -> list[dict]:
        items = list(env_manager)
        ids = {str(x["id"]) for x in items}
        split = kwargs.get("split")
        if not split:
            for name, rows in (
                ("train", self.dataloader.train_items),
                ("val", self.dataloader.val_items),
                ("test", self.dataloader.test_items),
            ):
                if ids == {str(x["id"]) for x in rows}:
                    split = name
                    break
        if not split:
            raise ValueError("rollout items do not match any complete official split")
        skill_dir = None
        if skill_content.strip():
            # Harbor's --skills-dir is a root whose direct child folders
            # contain SKILL.md; Pi then discovers the skill recursively.
            package_skill(skill_content, Path(out_dir) / "candidate")
            skill_dir = Path(out_dir) / "candidate"
        return self.runner.run_split(
            split,
            items,
            skill_dir=skill_dir,
            out_dir=out_dir,
            candidate_id=kwargs.get("candidate_id", "skillopt-candidate"),
        )

    def get_task_types(self) -> list[str]:
        return ["alfworld"] if self.runner.benchmark == "alfworld" else ["spreadsheet"]
