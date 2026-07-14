import json
from pathlib import Path
from typing import Any, Optional


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
