"""Skill files: each agent's instructions, versioned, in app/skills/<agent>.md.

Front matter sets the version, the model tier and how hard it should think.
The version is part of the cache key, so editing a skill and bumping its
version re-runs that agent instead of reusing old answers.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"


@dataclass(frozen=True)
class Skill:
    name: str
    version: str
    tier: str  # "reasoning" | "fast"
    thinking: str | None
    instructions: str


@lru_cache
def load(name: str) -> Skill:
    path = SKILLS_DIR / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path} has no front matter")
    _, front, body = text.split("---", 2)
    meta = yaml.safe_load(front) or {}
    return Skill(
        name=name,
        version=str(meta["version"]),
        tier=meta.get("tier", "reasoning"),
        thinking=meta.get("thinking"),
        instructions=body.strip(),
    )
