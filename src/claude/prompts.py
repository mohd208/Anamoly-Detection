from src.incident.types import Incident, IncidentDiagnostics


def extraction_prompt(raw_slack_text: str) -> str:
    return f"""The following is a raw Slack message text from a Datadog alert. Extract the
Kubernetes cluster name, namespace, and workload (deployment or pod) name it refers to.
Respond with ONLY a JSON object, no prose: {{"cluster": string|null, "namespace": string|null, "workload": string|null}}

Message:
\"\"\"
{raw_slack_text}
\"\"\""""


def analysis_prompt(
    incident: Incident,
    diagnostics: IncidentDiagnostics,
    fix_paths: list[str],
) -> str:
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
