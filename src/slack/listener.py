import logging

from slack_bolt import App

from src import config
from src.incident.parser import parse_incident
from src.orchestrator import handle_incident
from src.slack import formatter as fmt

logger = logging.getLogger("anomaly-agent.slack")


def create_slack_app() -> App:
    app = App(token=config.SLACK_BOT_TOKEN)

    @app.message()
    def on_message(message, say):
        channel = message.get("channel")
        logger.info("Received message event in channel %s (ts=%s)", channel, message.get("ts"))

        # Only react to plain messages (Datadog posts as a bot message with
        # text/attachments) in the configured incident channel.
        if channel != config.SLACK_INCIDENT_CHANNEL_ID:
            logger.info(
                "Ignoring message: channel %s does not match SLACK_INCIDENT_CHANNEL_ID=%s",
                channel, config.SLACK_INCIDENT_CHANNEL_ID,
            )
            return

        subtype = message.get("subtype")
        if subtype and subtype != "bot_message":
            logger.info("Ignoring message: unsupported subtype %s", subtype)
            return

        text = message.get("text", "")
        if not text:
            logger.info("Ignoring message: empty text")
            return

        logger.info("Parsing incident from message text: %r", text)
        incident = parse_incident(channel=channel, ts=message["ts"], text=text)

        if not incident:
            logger.warning("Could not parse an incident (cluster/namespace/workload) from this message")
            say(text=fmt.unresolved_incident_message(), thread_ts=message["ts"])
            return

        logger.info(
            "Parsed incident: cluster=%s namespace=%s workload=%s alert_type=%s",
            incident.cluster, incident.namespace, incident.workload, incident.alert_type,
        )

        handle_incident(
            incident,
            reply=lambda reply_text: say(text=reply_text, thread_ts=message["ts"]),
        )

    return app
