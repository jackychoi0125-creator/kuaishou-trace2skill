"""Validate and package SkillOpt text as a Pi-discoverable skill directory."""

from __future__ import annotations

import re
from pathlib import Path

import yaml


def package_skill(content: str, target: str | Path, *, name: str = "spreadsheet-workflow") -> Path:
    body = content.strip()
    if body.startswith("---"):
        frontmatter, sep, remainder = body[3:].partition("\n---")
        if not sep:
            raise ValueError("unclosed YAML frontmatter")
        body = remainder.lstrip("\r\n").strip()
        try:
            metadata = yaml.safe_load(frontmatter)
        except yaml.YAMLError as exc:
            raise ValueError("skill YAML frontmatter is invalid") from exc
        if not isinstance(metadata, dict) or not re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*", str(metadata.get("name", ""))
        ):
            raise ValueError("skill frontmatter must define a valid lowercase-hyphen name")
        if not isinstance(metadata.get("description"), str) or not metadata["description"].strip():
            raise ValueError("skill frontmatter must define a nonempty description")
        body = "---" + frontmatter + "\n---\n\n" + remainder.lstrip("\r\n").strip()
    else:
        body = (
            "---\nname: spreadsheet-workflow\ndescription: Use for spreadsheet editing, formulas, formatting, and workbook analysis tasks.\n---\n\n"
            + body
        )
    if not body.strip():
        raise ValueError("skill body cannot be empty")
    if re.search(r"(?i)(?:answer|expected result)\s*[:=]\s*[^\n]{0,100}\b(?:val|test|question\s*\d+)\b", body):
        raise ValueError("skill appears to contain a benchmark-specific answer; refusing to package")
    path = Path(target) / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body + "\n", encoding="utf-8")
    return path
