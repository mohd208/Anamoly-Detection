import json
import logging
import subprocess
from typing import Any, Optional

from app import config

logger = logging.getLogger("anomaly-agent.claude")

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
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"claude CLI exited {result.returncode}. stderr: {result.stderr.strip() or '(empty)'} "
            f"stdout: {result.stdout.strip() or '(empty)'}"
        )
    return result.stdout


def run_claude_json(prompt: str, **kwargs) -> Optional[dict[str, Any]]:
    """Runs a prompt and parses the CLI's JSON envelope, returning the inner
    `result` field parsed as JSON. Returns None if anything about the shape
    doesn't match, so callers can fall back gracefully instead of crashing
    the whole incident pipeline on a malformed response - but always logs
    the actual reason first, so a bad CLI flag or non-JSON response is
    diagnosable instead of a silent None."""
    try:
        stdout = run_claude(prompt, **kwargs)
    except subprocess.TimeoutExpired:
        logger.exception("claude CLI timed out")
        return None
    except Exception:
        logger.exception("claude CLI invocation failed")
        return None

    try:
        envelope = json.loads(stdout)
        result = envelope.get("result")
        result_text = result if isinstance(result, str) else json.dumps(result)
        return json.loads(result_text)
    except Exception:
        logger.error("Could not parse claude CLI output as JSON. Raw stdout:\n%s", stdout)
        return None


def extraction_prompt(raw_slack_text: str) -> str:
    return f"""The following is a raw Slack message text from a Datadog alert. Extract the
Kubernetes cluster name, namespace, and workload (deployment or pod) name it refers to.
Respond with ONLY a JSON object, no prose: {{"cluster": string|null, "namespace": string|null, "workload": string|null}}

Message:
\"\"\"
{raw_slack_text}
\"\"\""""


def analysis_prompt(incident, diagnostics, fix_paths: list[str]) -> str:
    """`incident` is an app.parser.Incident and `diagnostics` an
    app.k8s.IncidentDiagnostics - left untyped here to avoid a circular
    import (both of those modules import from this one)."""
    return f"""You are a Kubernetes/DevOps incident triage agent. You are running with file
access to a checked-out git repository (your current working directory) that owns the
deployment configuration for the affected workload.

INCIDENT
alert type: {incident.alert_type}
cluster: {incident.cluster}
namespace: {incident.namespace}
workload: {incident.workload}
title: {incident.title}
monitor url: {incident.monitor_url or "n/a"}

DIAGNOSTICS (read-only, gathered via kubectl before you were invoked)
--- kubectl describe pod ---
{diagnostics.describe_pod or "n/a"}

--- previous container logs (crash) ---
{diagnostics.previous_logs or "n/a"}

--- current container logs ---
{diagnostics.current_logs or "n/a"}

--- recent events ---
{diagnostics.events or "n/a"}

--- deployment manifest (live, from cluster) ---
{diagnostics.deployment_yaml or "n/a"}

TASK
1. Determine the root cause of this incident.
2. Classify it as exactly one of:
   - "devops_fix": the fix belongs in DevOps-owned files - Dockerfile, Kubernetes
     manifests, Helm charts, Terraform, or CI/CD workflow files.
   - "code_suggestion_only": the fix requires changing application source code.
3. If "devops_fix": make the fix directly in this repository's working tree, but you
   are ONLY allowed to modify files matching these glob patterns:
     {", ".join(fix_paths)}
   If you cannot find a fix confined to those paths, classify as
   "code_suggestion_only" instead. Do not commit or push - just edit the files,
   the caller handles git operations.
4. If "code_suggestion_only": do NOT edit any files. Instead produce a clear,
   actionable suggestion (including a code snippet/diff if useful) for a human
   engineer to apply.

Respond with ONLY a JSON object, no prose, matching exactly this shape:
{{
  "classification": "devops_fix" | "code_suggestion_only",
  "root_cause": string,
  "summary": string,
  "suggestion": string | null
}}"""
