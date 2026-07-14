import logging
import re
import time
from typing import Callable

from src import config
from src.claude.prompts import analysis_prompt
from src.claude.runner import run_claude_json
from src.github import pr as pr_module
from src.github.git_ops import checkout_fresh_branch, commit_and_push
from src.github.path_guard import enforce_path_allow_list
from src.github.repo_map import load_fix_paths, resolve_mapping
from src.incident.dedupe import IncidentDedupe
from src.incident.types import Incident
from src.k8s.diagnostics import gather_diagnostics
from src.k8s.eks import ensure_kubeconfig
from src.slack import formatter as fmt

logger = logging.getLogger("anomaly-agent.orchestrator")

dedupe = IncidentDedupe(config.STATE_DIR / "incident-cooldowns.json", config.INCIDENT_COOLDOWN_MINUTES)


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
        reply(fmt.cooldown_message(incident, cooldown_hit.get("pr_url")))
        return

    reply(fmt.investigating_message(incident))

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

        existing_pr = pr_module.find_existing_open_pr(config.GITHUB_TOKEN, mapping.repo, branch_prefix)
        if existing_pr:
            logger.info("Existing open PR found, skipping: %s", existing_pr)
            reply(fmt.cooldown_message(incident, existing_pr))
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
            reply(fmt.error_message(incident, "Claude did not return a parseable analysis"))
            return

        logger.info("Claude classification: %s", analysis.get("classification"))

        if analysis.get("classification") == "code_suggestion_only":
            reply(
                fmt.code_suggestion_message(
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
                fmt.code_suggestion_message(
                    incident,
                    analysis.get("root_cause", "unknown"),
                    analysis.get("suggestion") or "Root cause requires a fix outside the auto-fixable paths for this repo.",
                )
            )
            dedupe.mark_handled(incident)
            return

        commit_and_push(
            checkout.dir, checkout.branch, f"fix: {incident.alert_type} in {incident.namespace}/{incident.workload}"
        )

        pr_url = pr_module.open_pull_request(
            config.GITHUB_TOKEN,
            mapping.repo,
            checkout.branch,
            incident,
            analysis.get("root_cause", "unknown"),
            analysis.get("summary", ""),
            guard_result.allowed,
        )
        logger.info("Opened PR: %s", pr_url)

        reply(fmt.pr_opened_message(incident, pr_url, analysis.get("root_cause", "unknown"), analysis.get("summary", "")))
        dedupe.mark_handled(incident, pr_url)
    except Exception as err:  # noqa: BLE001 - top-level pipeline guard, reported back to Slack
        logger.exception("Incident pipeline failed")
        reply(fmt.error_message(incident, str(err)))
