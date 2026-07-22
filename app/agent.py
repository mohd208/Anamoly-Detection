import logging
import re
import time
from typing import Callable, Optional

from app import config
from app.claude import analysis_prompt, run_claude_json
from app.github import (
    checkout_fresh_branch,
    commit_and_push,
    enforce_path_allow_list,
    find_existing_open_pr,
    load_fix_paths,
    open_pull_request,
    resolve_mapping,
)
from app.parser import Incident
from app.state import IncidentDedupe
from app.k8s import ensure_kubeconfig, gather_diagnostics

logger = logging.getLogger("anomaly-agent.agent")

dedupe = IncidentDedupe(config.STATE_DIR / "incident-cooldowns.json", config.INCIDENT_COOLDOWN_MINUTES)


# --- Slack message templates ---

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


# --- pipeline ---

def _branch_name(incident: Incident) -> str:
    slug = re.sub(
        r"[^a-z0-9-]+", "-", f"{incident.namespace}-{incident.workload}-{incident.alert_type}".lower()
    )
    return f"fix/incident-{slug}-{int(time.time())}"


def handle_incident(incident: Incident, reply: Callable[[str], None]) -> None:
    logger.info(
        "Handling incident: cluster=%s namespace=%s workload=%s alert_type=%s",
        incident.cluster, incident.namespace, incident.workload, incident.alert_type,
    )

    cooldown_hit = dedupe.check_cooldown(incident)
    if cooldown_hit:
        logger.info("Cooldown hit, skipping: %s", cooldown_hit)
        reply(cooldown_message(incident, cooldown_hit.get("pr_url")))
        return

    reply(investigating_message(incident))

    mapping = resolve_mapping(incident)
    logger.info("Resolved repo=%s region=%s", mapping.repo, mapping.region)

    try:
        fix_paths = load_fix_paths(config.FIX_PATHS_PATH)

        logger.info("Generating kubeconfig for cluster %s (region %s)", incident.cluster, mapping.region)
        kubeconfig_path = ensure_kubeconfig(incident.cluster, mapping.region, config.WORKDIR)

        logger.info("Gathering kubectl diagnostics for %s/%s", incident.namespace, incident.workload)
        diagnostics = gather_diagnostics(incident, kubeconfig_path)

        branch = _branch_name(incident)
        branch_prefix = f"fix/incident-{incident.namespace}-{incident.workload}-{incident.alert_type}".lower()

        existing_pr = find_existing_open_pr(config.GITHUB_TOKEN, mapping.repo, branch_prefix)
        if existing_pr:
            logger.info("Existing open PR found, skipping: %s", existing_pr)
            reply(cooldown_message(incident, existing_pr))
            dedupe.mark_handled(incident, existing_pr)
            return

        logger.info("Cloning %s and checking out branch %s", mapping.repo, branch)
        checkout = checkout_fresh_branch(mapping.repo, config.WORKDIR, branch, config.GITHUB_TOKEN)

        logger.info("Running Claude root-cause analysis in %s", checkout.dir)
        analysis = run_claude_json(
            analysis_prompt(incident, diagnostics, fix_paths),
            cwd=str(checkout.dir),
            add_dirs=[str(checkout.dir)],
        )

        if not analysis:
            logger.error("Claude did not return a parseable analysis")
            reply(error_message(incident, "Claude did not return a parseable analysis"))
            return

        logger.info("Claude classification: %s", analysis.get("classification"))

        if analysis.get("classification") == "code_suggestion_only":
            reply(
                code_suggestion_message(
                    incident,
                    analysis.get("root_cause", "unknown"),
                    analysis.get("suggestion") or "(no suggestion text returned)",
                )
            )
            dedupe.mark_handled(incident)
            return

        guard_result = enforce_path_allow_list(checkout.dir, fix_paths)
        logger.info("Path guard: allowed=%s reverted=%s", guard_result.allowed, guard_result.reverted)

        if not guard_result.allowed:
            reply(
                code_suggestion_message(
                    incident,
                    analysis.get("root_cause", "unknown"),
                    analysis.get("suggestion") or "Root cause requires a fix outside the auto-fixable paths for this repo.",
                )
            )
            dedupe.mark_handled(incident)
            return

        commit_and_push(
            checkout.dir,
            checkout.branch,
            f"fix: {incident.alert_type} in {incident.namespace}/{incident.workload}",
            mapping.repo,
            config.GITHUB_TOKEN,
        )

        pr_url = open_pull_request(
            config.GITHUB_TOKEN,
            mapping.repo,
            checkout.branch,
            incident,
            analysis.get("root_cause", "unknown"),
            analysis.get("summary", ""),
            guard_result.allowed,
        )
        logger.info("Opened PR: %s", pr_url)

        reply(pr_opened_message(incident, pr_url, analysis.get("root_cause", "unknown"), analysis.get("summary", "")))
        dedupe.mark_handled(incident, pr_url)
    except Exception as err:  # noqa: BLE001 - top-level pipeline guard, reported back to Slack
        logger.exception("Incident pipeline failed")
        reply(error_message(incident, str(err)))
