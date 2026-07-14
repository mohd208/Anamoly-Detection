import json
import subprocess
from typing import Any, Optional

from src import config

# NOTE: exact flag names below (`-p`, `--output-format`, `--permission-mode`,
# `--add-dir`) are current as of this writing but should be re-verified with
# `claude --help` on the actual EC2 host - the CLI evolves and flags can be
# renamed between versions. This function intentionally isolates all of that
# so a version bump only means editing this one file.


def run_claude(
    prompt: str,
    cwd: Optional[str] = None,
    add_dirs: Optional[list[str]] = None,
    permission_mode: str = "acceptEdits",
    timeout_seconds: int = 300,
) -> str:
    """Runs a prompt through the already-authenticated `claude` CLI session and returns raw stdout."""
    args = [config.CLAUDE_BIN, "-p", prompt, "--output-format", "json", "--permission-mode", permission_mode]
    for directory in add_dirs or []:
        args += ["--add-dir", directory]

    result = subprocess.run(
        args,
        cwd=cwd,
        timeout=timeout_seconds,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def run_claude_json(prompt: str, **kwargs) -> Optional[dict[str, Any]]:
    """Runs a prompt and parses the CLI's JSON envelope, returning the inner
    `result` field parsed as JSON. Returns None if anything about the shape
    doesn't match, so callers can fall back gracefully instead of crashing
    the whole incident pipeline on a malformed response."""
    try:
        stdout = run_claude(prompt, **kwargs)
        envelope = json.loads(stdout)
        result = envelope.get("result")
        result_text = result if isinstance(result, str) else json.dumps(result)
        return json.loads(result_text)
    except Exception:
        return None
