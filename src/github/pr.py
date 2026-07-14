from typing import Optional

from github import Github

from src.github.git_ops import DEFAULT_BRANCH
from src.incident.types import Incident


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
