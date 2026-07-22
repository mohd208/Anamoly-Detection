import logging
from typing import Any

from slack_bolt import App

from app import config
from app.agent import handle_incident, unresolved_incident_message
from app.parser import parse_incident

logger = logging.getLogger("anomaly-agent.slack")


def _walk_blocks_for_text(nodes: Any, texts: list[str]) -> None:
    """Slack Block Kit nests text inside section/context/rich_text blocks in
    several different shapes - recursively collect every string found under
    a "text" key rather than special-casing each block type."""
    if isinstance(nodes, dict):
        text_value = nodes.get("text")
        if isinstance(text_value, str):
            texts.append(text_value)
        elif isinstance(text_value, dict):
            _walk_blocks_for_text(text_value, texts)
        for key in ("elements", "fields", "blocks"):
            _walk_blocks_for_text(nodes.get(key), texts)
    elif isinstance(nodes, list):
        for item in nodes:
            _walk_blocks_for_text(item, texts)


def _extract_text_from_event(event: dict) -> str:
    """Datadog (and similar integrations) don't always populate the
    top-level `text` field - rich alert cards (the ones with "Mute Monitor"/
    "Declare Incident" buttons) are delivered entirely via `blocks` and/or
    legacy `attachments` instead. Collect text from all of these so the
    incident parser has something to scan regardless of which shape a given
    notification used."""
    parts: list[str] = []

    text = event.get("text")
    if text:
        parts.append(text)

    for attachment in event.get("attachments") or []:
        for key in ("pretext", "title", "text", "fallback"):
            value = attachment.get(key)
            if value:
                parts.append(value)
        _walk_blocks_for_text(attachment.get("blocks"), parts)

    _walk_blocks_for_text(event.get("blocks"), parts)

    return "\n".join(parts)


def create_slack_app() -> App:
    app = App(token=config.SLACK_BOT_TOKEN)

    # NOTE: deliberately @app.event("message") and not @app.message() - Bolt's
    # message() decorator has built-in filtering that silently drops certain
    # message shapes, including bot-integration alerts like Datadog's (it logs
    # "Unhandled request" and suggests this exact fix). event("message") gets
    # the raw event with no extra filtering; we do all filtering ourselves.
    @app.event("message")
    def on_message(event, say):
        channel = event.get("channel")
        logger.info("Received message event in channel %s (ts=%s)", channel, event.get("ts"))

        # Only react to messages in the configured incident channel.
        if channel != config.SLACK_INCIDENT_CHANNEL_ID:
            logger.info(
                "Ignoring message: channel %s does not match SLACK_INCIDENT_CHANNEL_ID=%s",
                channel, config.SLACK_INCIDENT_CHANNEL_ID,
            )
            return

        # Datadog (and similar integrations) post as a bot message - accept those,
        # but skip other subtypes (message_changed, channel_join, etc).
        subtype = event.get("subtype")
        if subtype and subtype != "bot_message":
            logger.info("Ignoring message: unsupported subtype %s", subtype)
            return

        text = _extract_text_from_event(event)
        if not text:
            logger.info("Ignoring message: no text found in text, blocks, or attachments")
            return

        logger.info("Parsing incident from message text: %r", text)
        incident = parse_incident(channel=channel, ts=event["ts"], text=text)

        if not incident:
            logger.warning("Could not parse an incident (cluster/namespace/workload) from this message")
            say(text=unresolved_incident_message(), thread_ts=event["ts"])
            return

        logger.info(
            "Parsed incident: cluster=%s namespace=%s workload=%s alert_type=%s",
            incident.cluster, incident.namespace, incident.workload, incident.alert_type,
        )

        handle_incident(
            incident,
            reply=lambda reply_text: say(text=reply_text, thread_ts=event["ts"]),
        )

    return app
