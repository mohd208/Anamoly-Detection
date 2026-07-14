import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


SLACK_BOT_TOKEN = _required("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = _required("SLACK_APP_TOKEN")
SLACK_INCIDENT_CHANNEL_ID = _required("SLACK_INCIDENT_CHANNEL_ID")

GITHUB_TOKEN = _required("GITHUB_TOKEN")

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")

WORKDIR = Path(os.environ.get("WORKDIR", ROOT_DIR / "work"))
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT_DIR / "state"))
REPO_MAP_PATH = Path(os.environ.get("REPO_MAP_PATH", ROOT_DIR / "config" / "repo-map.yaml"))

INCIDENT_COOLDOWN_MINUTES = int(os.environ.get("INCIDENT_COOLDOWN_MINUTES", "30"))
