from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from src.github.git_ops import changed_files, discard_file


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
