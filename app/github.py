import shutil
import subprocess
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Optional

import yaml
from github import Github

from app import config
from app.parser import Incident

DEFAULT_BRANCH = "main"


# --- repo resolution ---

@dataclass
class RepoMapping:
    repo: str  # "owner/name"
    region: str


def resolve_mapping(incident: Incident) -> RepoMapping:
    """cluster/namespace come dynamically from the Slack incident itself. If
    GITHUB_REPO is set, every incident is pinned to that one repo (useful for
    testing / single-repo setups). Otherwise the repo is computed directly as
    f"{GITHUB_ORG}/{namespace}" - this assumes namespace names match GitHub
    repo names exactly."""
    repo = config.GITHUB_REPO or f"{config.GITHUB_ORG}/{incident.namespace}"
    return RepoMapping(repo=repo, region=config.AWS_REGION)


def load_fix_paths(file_path: Path) -> list[str]:
    with open(file_path, "r", encoding="utf-8") as f:
        parsed = yaml.safe_load(f) or {}

    fix_paths = parsed.get("fix_paths")
    if not fix_paths:
        raise ValueError(f"No fix_paths found in {file_path}")
    return fix_paths


# --- git operations ---

@dataclass
class RepoCheckout:
    dir: Path
    branch: str


def _git(cwd: Path, args: list[str]) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout


def checkout_fresh_branch(repo: str, workdir: Path, branch_name: str, github_token: str) -> RepoCheckout:
    """Clones a shallow checkout of `owner/repo` into `workdir` and creates a
    fresh branch off DEFAULT_BRANCH. The token is only ever passed via the
    remote URL for this process's git invocations - never written to disk or
    logged."""
    repo_dir = workdir / repo.replace("/", "__") / branch_name
    shutil.rmtree(repo_dir, ignore_errors=True)
    repo_dir.parent.mkdir(parents=True, exist_ok=True)

    remote_url = f"https://x-access-token:{github_token}@github.com/{repo}.git"
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", DEFAULT_BRANCH, remote_url, str(repo_dir)],
        check=True,
        capture_output=True,
        text=True,
    )

    _git(repo_dir, ["checkout", "-b", branch_name])
    _git(repo_dir, ["config", "user.name", "anomaly-agent"])
    _git(repo_dir, ["config", "user.email", "anomaly-agent@users.noreply.github.com"])

    return RepoCheckout(dir=repo_dir, branch=branch_name)


def changed_files(repo_dir: Path) -> list[str]:
    status = _git(repo_dir, ["status", "--porcelain"])
    files = []
    for line in status.splitlines():
        line = line.strip()
        if not line:
            continue
        files.append(line.split(maxsplit=1)[1])
    return files


def discard_file(repo_dir: Path, rel_path: str) -> None:
    """Handles both modified-tracked-files (checkout) and newly created files (rm)."""
    try:
        _git(repo_dir, ["checkout", "--", rel_path])
    except subprocess.CalledProcessError:
        (repo_dir / rel_path).unlink(missing_ok=True)


def commit_and_push(repo_dir: Path, branch: str, message: str) -> None:
    _git(repo_dir, ["add", "-A"])
    _git(repo_dir, ["commit", "-m", message])
    _git(repo_dir, ["push", "-u", "origin", branch])


# --- path allow-list enforcement ---

@dataclass
class GuardResult:
    allowed: list[str]
    reverted: list[str]


def _is_allowed(file: str, fix_paths: list[str]) -> bool:
    for pattern in fix_paths:
        if fnmatch(file, pattern):
            return True
        # fnmatch treats "/" as a literal character, so "**/Dockerfile*" would
        # otherwise only match nested paths (e.g. "backend/Dockerfile") and
        # miss a bare top-level "Dockerfile". Also try the pattern with its
        # leading recursive-directory prefix stripped.
        if pattern.startswith("**/") and fnmatch(file, pattern[len("**/"):]):
            return True
    return False


def enforce_path_allow_list(repo_dir: Path, fix_paths: list[str]) -> GuardResult:
    """The actual enforcement point: after Claude has (possibly) edited files
    in `repo_dir`, this inspects the real `git status` output and
    hard-reverts anything outside the repo's allow-list, regardless of what
    the prompt asked for. Prompt instructions are a request; this is the
    guarantee."""
    allowed, reverted = [], []

    for file in changed_files(repo_dir):
        if _is_allowed(file, fix_paths):
            allowed.append(file)
        else:
            discard_file(repo_dir, file)
            reverted.append(file)

    return GuardResult(allowed=allowed, reverted=reverted)


# --- pull requests ---

def open_pull_request(
    github_token: str,
    repo: str,
    branch: str,
    incident: Incident,
    root_cause: str,
    summary: str,
    changed_files: list[str],
) -> str:
    gh = Github(github_token)
    gh_repo = gh.get_repo(repo)

    files_list = "\n".join(f"- `{f}`" for f in changed_files)
    body = f"""**Auto-generated fix for incident**: `{incident.alert_type}` in `{incident.namespace}/{incident.workload}` (cluster `{incident.cluster}`)

### Root cause
{root_cause}

### Summary of changes
{summary}

### Files changed
{files_list}

{f"Datadog monitor: {incident.monitor_url}" if incident.monitor_url else ""}

This PR was opened automatically. **It will not be auto-merged** - please review before merging.
"""

    pr = gh_repo.create_pull(
        title=f"fix: {incident.alert_type} in {incident.namespace}/{incident.workload}",
        head=branch,
        base=DEFAULT_BRANCH,
        body=body,
    )
    return pr.html_url


def find_existing_open_pr(github_token: str, repo: str, branch_prefix: str) -> Optional[str]:
    """Avoids opening a duplicate PR if one for this incident's branch prefix is already open."""
    gh = Github(github_token)
    gh_repo = gh.get_repo(repo)

    for pr in gh_repo.get_pulls(state="open"):
        if pr.head.ref.startswith(branch_prefix):
            return pr.html_url
    return None
