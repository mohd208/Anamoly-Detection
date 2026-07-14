from dataclasses import dataclass
from pathlib import Path

import yaml

from src import config
from src.incident.types import Incident


@dataclass
class RepoMapping:
    repo: str  # "owner/name"
    region: str


def resolve_mapping(incident: Incident) -> RepoMapping:
    """cluster/namespace come dynamically from the Slack incident itself, so
    the repo is computed directly rather than looked up in a static table -
    this assumes namespace names match GitHub repo names exactly."""
    return RepoMapping(repo=f"{config.GITHUB_ORG}/{incident.namespace}", region=config.AWS_REGION)


def load_fix_paths(file_path: Path) -> list[str]:
    with open(file_path, "r", encoding="utf-8") as f:
        parsed = yaml.safe_load(f) or {}

    fix_paths = parsed.get("fix_paths")
    if not fix_paths:
        raise ValueError(f"No fix_paths found in {file_path}")
    return fix_paths
