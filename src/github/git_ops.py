import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BRANCH = "main"


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
