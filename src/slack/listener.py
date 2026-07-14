from slack_bolt import App

from src import config
from src.incident.parser import parse_incident
from src.orchestrator import handle_incident
from src.slack import formatter as fmt


def create_slack_app() -> App:
    app = App(token=config.SLACK_BOT_TOKEN)

    @app.message()
    def on_message(message, say):
        # Only react to plain messages (Datadog posts as a bot message with
        # text/attachments) in the configured incident channel.
        if message.get("channel") != config.SLACK_INCIDENT_CHANNEL_ID:
            return
        subtype = message.get("subtype")
        if subtype and subtype != "bot_message":
            return

        text = message.get("text", "")
        if not text:
            return

        incident = parse_incident(channel=message["channel"], ts=message["ts"], text=text)

        if not incident:
            say(text=fmt.unresolved_incident_message(), thread_ts=message["ts"])
            return

        handle_incident(
            incident,
            reply=lambda reply_text: say(text=reply_text, thread_ts=message["ts"]),
        )

    return app
