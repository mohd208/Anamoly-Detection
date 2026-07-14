from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from src.incident.types import Incident


@dataclass
class RepoMapping:
    repo: str  # "owner/name"
    region: str
    fix_paths: list[str]


def _matches(pattern: str, value: str) -> bool:
    return pattern == "*" or pattern.lower() == value.lower()


def load_repo_map(file_path: Path) -> list[dict]:
    with open(file_path, "r", encoding="utf-8") as f:
        parsed = yaml.safe_load(f)
    mappings = parsed.get("mappings") if parsed else None
    if not mappings:
        raise ValueError(f"No mappings found in {file_path}")
    return mappings


def resolve_mapping(mappings: list[dict], incident: Incident) -> Optional[RepoMapping]:
    for entry in mappings:
        if _matches(entry["cluster"], incident.cluster) and _matches(entry["namespace"], incident.namespace):
            return RepoMapping(repo=entry["repo"], region=entry["region"], fix_paths=entry["fix_paths"])
    return None
