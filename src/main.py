from slack_bolt.adapter.socket_mode import SocketModeHandler

from src import config
from src.slack.listener import create_slack_app


def main() -> None:
    app = create_slack_app()
    handler = SocketModeHandler(app, config.SLACK_APP_TOKEN)
    print(f"anomaly-agent running (Socket Mode), watching channel {config.SLACK_INCIDENT_CHANNEL_ID}")
    handler.start()


if __name__ == "__main__":
    main()
