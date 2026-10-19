"""Deterministic loader for Harbor's frozen benchmark split manifests."""

from __future__ import annotations

import json
from pathlib import Path

from skillopt.datasets.base import BatchSpec, SplitDataLoader


class HarborSplitDataLoader(SplitDataLoader):
    """Read official Harbor split manifests without creating new splits."""

    def __init__(self, split_dir: str, seed: int = 42) -> None:
        super().__init__(split_dir=split_dir, split_mode="split_dir", seed=seed)

    def load_split_items(self, split_path: str) -> list[dict]:
        files = sorted(Path(split_path).glob("*.json"))
        if len(files) != 1:
            raise ValueError(f"expected one Harbor split manifest in {split_path}, found {len(files)}")
        rows = json.loads(files[0].read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError(f"Harbor split must be a JSON list: {files[0]}")
        return [{**row, "id": str(row["id"])} for row in rows]

    def build_train_batch(self, batch_size: int, seed: int, **kwargs) -> BatchSpec:
        rows = list(self.train_items)
        if batch_size < len(rows):
            raise ValueError("Harbor Kit does not expose arbitrary task-ID selection; use a full split rollout")
        return BatchSpec("train", "train", seed, len(rows), payload=rows)

    def build_eval_batch(self, env_num: int, split: str, seed: int, **kwargs) -> BatchSpec:
        alias = {"valid_seen": "val", "selection": "val", "valid_unseen": "test"}.get(split, split)
        rows = list({"train": self.train_items, "val": self.val_items, "test": self.test_items}[alias])
        if env_num < len(rows):
            raise ValueError("Harbor evaluation requires the full official split; partial ID selection is unavailable")
        return BatchSpec("eval", alias, seed, len(rows), payload=rows)
