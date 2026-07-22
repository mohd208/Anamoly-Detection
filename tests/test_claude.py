import json
from unittest.mock import MagicMock, patch

from app.claude import run_claude_json


def _envelope(result):
    return json.dumps({"type": "result", "subtype": "success", "result": result})


def test_run_claude_json_parses_pure_json_result():
    with patch("app.claude.run_claude", return_value=_envelope('{"classification": "devops_fix"}')):
        assert run_claude_json("prompt") == {"classification": "devops_fix"}


def test_run_claude_json_extracts_json_from_prose_plus_markdown_fence():
    # Mirrors a real observed claude response: narration, then the JSON
    # wrapped in a ```json fence, instead of pure JSON as asked for.
    result_text = (
        "Repo confirmed empty aside from a README - no manifests exist.\n\n"
        "```json\n"
        '{\n  "classification": "code_suggestion_only",\n  "root_cause": "exit 1",\n'
        '  "summary": "demo pod",\n  "suggestion": "fix the command"\n}\n'
        "```"
    )
    with patch("app.claude.run_claude", return_value=_envelope(result_text)):
        parsed = run_claude_json("prompt")

    assert parsed == {
        "classification": "code_suggestion_only",
        "root_cause": "exit 1",
        "summary": "demo pod",
        "suggestion": "fix the command",
    }


def test_run_claude_json_returns_none_when_no_json_object_present():
    with patch("app.claude.run_claude", return_value=_envelope("just plain prose, no object here")):
        assert run_claude_json("prompt") is None


def test_run_claude_json_returns_none_when_cli_raises():
    with patch("app.claude.run_claude", side_effect=RuntimeError("claude CLI exited 1")):
        assert run_claude_json("prompt") is None
