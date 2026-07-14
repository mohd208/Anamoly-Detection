import re
from datetime import datetime, timezone
from typing import Optional

from src.claude.prompts import extraction_prompt
from src.claude.runner import run_claude_json
from src.incident.types import Incident

# Datadog's Slack integration renders monitor tags as space-separated
# `key:value` tokens in the message text (e.g. `cluster_name:prod-eks
# kube_namespace:payments pod_name:payments-7f9...`). We try these known
# keys first since they're reliably present; only fall back to a Claude
# call when the required fields can't be found this way.
TAG_ALIASES = {
    "cluster": ["cluster_name", "cluster", "kube_cluster_name", "eks_cluster"],
    "namespace": ["kube_namespace", "namespace", "ns"],
    "workload": ["kube_deployment", "deployment", "pod_name", "kube_pod_name", "pod"],
}

ALERT_PATTERNS = [
    (re.compile(r"crashloopbackoff", re.I), "CrashLoopBackOff"),
    (re.compile(r"oomkilled|out of memory", re.I), "OOMKilled"),
    (re.compile(r"imagepullbackoff", re.I), "ImagePullBackOff"),
    (re.compile(r"errimagepull", re.I), "ErrImagePull"),
    (re.compile(r"(readiness|liveness) probe failed", re.I), "ProbeFailure"),
]

MONITOR_URL_PATTERN = re.compile(r"https?://[^\s|>]*datadoghq\.com[^\s|>]*", re.I)


def _extract_tag(text: str, keys: list[str]) -> Optional[str]:
    for key in keys:
        match = re.search(rf"\b{re.escape(key)}:([^\s,]+)", text, re.I)
        if match:
            return match.group(1).strip('"')
    return None


def _detect_alert_type(text: str) -> str:
    for pattern, alert_type in ALERT_PATTERNS:
        if pattern.search(text):
            return alert_type
    return "Unknown"


def _extract_monitor_url(text: str) -> Optional[str]:
    match = MONITOR_URL_PATTERN.search(text)
    return match.group(0) if match else None


def parse_incident(channel: str, ts: str, text: str, title: Optional[str] = None) -> Optional[Incident]:
    cluster = _extract_tag(text, TAG_ALIASES["cluster"])
    namespace = _extract_tag(text, TAG_ALIASES["namespace"])
    workload = _extract_tag(text, TAG_ALIASES["workload"])
    alert_type = _detect_alert_type(f"{title or ''} {text}")

    if not (cluster and namespace and workload):
        fallback = run_claude_json(extraction_prompt(text)) or {}
        cluster = cluster or fallback.get("cluster")
        namespace = namespace or fallback.get("namespace")
        workload = workload or fallback.get("workload")

    if not (cluster and namespace and workload):
        # Not enough signal to act on - let a human triage it manually.
        return None

    return Incident(
        slack_message_ts=ts,
        slack_channel=channel,
        cluster=cluster,
        namespace=namespace,
        workload=workload,
        alert_type=alert_type,
        title=title or text[:120],
        raw_text=text,
        monitor_url=_extract_monitor_url(text),
        detected_at=datetime.now(timezone.utc).isoformat(),
    )
