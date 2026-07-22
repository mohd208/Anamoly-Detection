import logging

from slack_bolt import App

from app import config
from app.agent import handle_incident, unresolved_incident_message
from app.parser import parse_incident

logger = logging.getLogger("anomaly-agent.slack")


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

        text = event.get("text", "")
        if not text:
            logger.info("Ignoring message: empty text")
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
