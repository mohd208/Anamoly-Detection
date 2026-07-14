from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.incident.types import Incident
from src.state.store import JsonStore


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
