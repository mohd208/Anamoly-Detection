import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from slack_bolt.adapter.socket_mode import SocketModeHandler

from app import config
from app.listener import create_slack_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger("anomaly-agent")


def _run_slack_listener() -> None:
    """Slack Bolt's Socket Mode handler is a blocking call that manages its
    own connection loop - it runs on a background thread so uvicorn's async
    event loop (serving /health) is never blocked by it."""
    slack_app = create_slack_app()
    handler = SocketModeHandler(slack_app, config.SLACK_APP_TOKEN)
    logger.info("Slack listener starting, watching channel %s", config.SLACK_INCIDENT_CHANNEL_ID)
    handler.start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    thread = threading.Thread(target=_run_slack_listener, daemon=True, name="slack-socket-mode")
    thread.start()
    app.state.slack_thread = thread
    yield


app = FastAPI(title="anomaly-agent", lifespan=lifespan)


@app.get("/health")
def health(request: Request) -> dict:
    thread: threading.Thread = request.app.state.slack_thread
    alive = thread.is_alive()
    return {"status": "ok" if alive else "degraded", "slack_listener_alive": alive}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
