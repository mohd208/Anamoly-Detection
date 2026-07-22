import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.parser import Incident


class JsonStore:
    """Minimal JSON-file key/value store. Good enough for single-instance
    incident-cooldown bookkeeping - swap for SQLite/Redis if this ever needs
    to run as more than one replica."""

    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)

    def _load(self) -> dict:
        try:
            return json.loads(self.file_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def get(self, key: str) -> Optional[Any]:
        return self._load().get(key)

    def set(self, key: str, value: Any) -> None:
        data = self._load()
        data[key] = value
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def fingerprint(incident: Incident) -> str:
    return "|".join(
        [incident.cluster, incident.namespace, incident.workload, incident.alert_type]
    ).lower()


class IncidentDedupe:
    def __init__(self, state_file_path: Path, cooldown_minutes: int):
        self.store = JsonStore(state_file_path)
        self.cooldown_minutes = cooldown_minutes

    def check_cooldown(self, incident: Incident) -> Optional[dict]:
        """Returns the existing record if this incident is still within its cooldown window."""
        record = self.store.get(fingerprint(incident))
        if not record:
            return None

        last_seen = datetime.fromisoformat(record["last_seen_at"])
        elapsed_minutes = (datetime.now(timezone.utc) - last_seen).total_seconds() / 60
        return record if elapsed_minutes < self.cooldown_minutes else None

    def mark_handled(self, incident: Incident, pr_url: Optional[str] = None) -> None:
        self.store.set(
            fingerprint(incident),
            {"last_seen_at": datetime.now(timezone.utc).isoformat(), "pr_url": pr_url},
        )
