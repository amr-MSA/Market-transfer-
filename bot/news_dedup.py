import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


class NewsDedupStore:
    """Seven-day normalized event cache.

    The JSON contains only structured event identities. Source URLs/titles are
    intentionally not used as the duplicate key.
    """

    def __init__(self, path, retention_days=7):
        self.path = Path(path)
        self.retention = timedelta(days=retention_days)

    def load(self):
        if not self.path.exists():
            return {"updated_at": None, "events": []}
        try:
            with self.path.open(encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or not isinstance(data.get("events", []), list):
                return {"updated_at": None, "events": []}
            return {
                "updated_at": data.get("updated_at"),
                "events": data.get("events", []),
            }
        except (OSError, ValueError):
            return {"updated_at": None, "events": []}

    def prune(self, data, now=None):
        now = now or datetime.now(timezone.utc)
        cutoff = now - self.retention
        kept = []

        for event in data.get("events", []):
            marker = event.get("seen_at")
            try:
                when = datetime.fromisoformat(marker.replace("Z", "+00:00"))
            except (AttributeError, ValueError):
                continue
            if when >= cutoff:
                kept.append(event)

        data["events"] = kept
        return data

    @staticmethod
    def normalize(value):
        if not value:
            return None
        return " ".join(str(value).casefold().split())

    def key(self, event):
        return (
            self.normalize(event.get("entity_type")),
            self.normalize(event.get("type")),
            self.normalize(event.get("player")),
            self.normalize(event.get("from")),
            self.normalize(event.get("to")),
        )

    def contains(self, data, event):
        target = self.key(event)
        for previous in data.get("events", []):
            if self.key(previous) == target:
                return True
        return False

    def add(self, data, event, now=None):
        now = now or datetime.now(timezone.utc)
        record = dict(event)
        record["seen_at"] = now.isoformat()
        data.setdefault("events", []).append(record)
        data["updated_at"] = now.isoformat()

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, self.path)
