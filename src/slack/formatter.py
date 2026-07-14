from typing import Optional

from src.incident.types import Incident


def investigating_message(incident: Incident) -> str:
    return f":mag: Investigating *{incident.alert_type}* on `{incident.namespace}/{incident.workload}` (cluster `{incident.cluster}`)..."


def cooldown_message(incident: Incident, previous_pr_url: Optional[str] = None) -> str:
    suffix = f" Previous fix: {previous_pr_url}" if previous_pr_url else ""
    return (
        f":hourglass_flowing_sand: Already handled a matching `{incident.alert_type}` incident on "
        f"`{incident.namespace}/{incident.workload}` recently - skipping to avoid duplicate work.{suffix}"
    )


def unresolved_incident_message() -> str:
    return ":warning: Couldn't confidently determine the cluster/namespace/workload for this alert - needs manual triage."


def pr_opened_message(incident: Incident, pr_url: str, root_cause: str, summary: str) -> str:
    return (
        f":white_check_mark: Root cause found for *{incident.alert_type}* on "
        f"`{incident.namespace}/{incident.workload}`:\n"
        f"> {root_cause}\n\n"
        f"Opened a PR with a fix: {pr_url}\n"
        f"_{summary}_\n\n"
        f":warning: This PR will *not* auto-merge - please review."
    )


def code_suggestion_message(incident: Incident, root_cause: str, suggestion: str) -> str:
    return (
        f":bulb: Root cause for *{incident.alert_type}* on `{incident.namespace}/{incident.workload}` looks like an "
        f"*application code* issue, so I didn't auto-fix it:\n"
        f"> {root_cause}\n\n"
        f"*Suggested fix:*\n{suggestion}\n\n"
        f":point_up: Needs a human to apply this in the app repo."
    )


def error_message(incident: Incident, error: str) -> str:
    return (
        f":x: Failed to complete root-cause analysis for *{incident.alert_type}* on "
        f"`{incident.namespace}/{incident.workload}`: `{error}`"
    )
