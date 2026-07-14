from dataclasses import dataclass
from typing import Optional


@dataclass
class Incident:
    slack_message_ts: str
    slack_channel: str
    cluster: str
    namespace: str
    workload: str  # deployment/pod name, best-effort
    alert_type: str
    title: str
    raw_text: str
    detected_at: str
    monitor_url: Optional[str] = None


@dataclass
class IncidentDiagnostics:
    describe_pod: Optional[str] = None
    previous_logs: Optional[str] = None
    current_logs: Optional[str] = None
    events: Optional[str] = None
    deployment_yaml: Optional[str] = None


@dataclass
class ClaudeAnalysisResult:
    classification: str  # "devops_fix" | "code_suggestion_only"
    root_cause: str
    summary: str
    suggestion: Optional[str] = None
