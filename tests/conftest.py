import os

# src/config.py requires these at import time; tests never talk to Slack/GitHub
# for real, so dummy values are enough to let modules import cleanly.
os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")
os.environ.setdefault("SLACK_INCIDENT_CHANNEL_ID", "C0000000000")
os.environ.setdefault("GITHUB_TOKEN", "ghp-test")
