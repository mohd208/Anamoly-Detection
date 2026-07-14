from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from src.github.git_ops import changed_files, discard_file


@dataclass
class GuardResult:
    allowed: list[str]
    reverted: list[str]


def _is_allowed(file: str, fix_paths: list[str]) -> bool:
    return any(fnmatch(file, pattern) for pattern in fix_paths)


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
