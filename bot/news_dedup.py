import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


class NewsDedupStore:
    """TTL cache for Gemini-classified events and inspected article IDs.

    Event identity is built from type, from, to and the named person/player. Records remain
    for a full retention window from their own ``seen_at`` timestamp; calendar
    week boundaries never delete recent records.
    """

    def __init__(self, path, retention_days=7):
        self.path = Path(path)
        self.retention = timedelta(days=retention_days)  # Compatibility for callers from older versions.

    def load(self):
        empty = {"week_start": None, "updated_at": None, "events": [], "articles": []}
        if not self.path.exists():
            return empty
        try:
            with self.path.open(encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError, TypeError):
            return empty
        if not isinstance(data, dict) or not isinstance(data.get("events", []), list):
            return empty
        return {
            "week_start": data.get("week_start"),
            "updated_at": data.get("updated_at"),
            "events": data.get("events", []),
            "articles": data.get("articles", []) if isinstance(data.get("articles", []), list) else [],
        }

    def prune(self, data, now=None):
        now = now or datetime.now(timezone.utc)
        cutoff = now.astimezone(timezone.utc) - self.retention

        def recent(record):
            try:
                seen = datetime.fromisoformat(str(record.get("seen_at")).replace("Z", "+00:00"))
                if seen.tzinfo is None:
                    seen = seen.replace(tzinfo=timezone.utc)
                return seen.astimezone(timezone.utc) >= cutoff
            except (AttributeError, TypeError, ValueError):
                # Legacy records without timestamps are retained once rather
                # than discarded silently during migration.
                return True

        data["events"] = [record for record in data.get("events", []) if recent(record)]
        data["articles"] = [record for record in data.get("articles", []) if recent(record)]
        data["week_start"] = None
        data["updated_at"] = now.astimezone(timezone.utc).isoformat()
        return data

    @staticmethod
    def normalize(value):
        return " ".join(str(value or "").casefold().split()) or None

    def key(self, event):
        return (
            self.normalize(event.get("type")),
            self.normalize(event.get("from")),
            self.normalize(event.get("to")),
            self.normalize(event.get("player")),
            self.normalize(event.get("person")),
        )

    def contains(self, data, event):
        target = self.key(event)
        return any(self.key(previous) == target for previous in data.get("events", []))

    @staticmethod
    def has_article(data, article_id):
        return str(article_id or "") in {str(article.get("id")) for article in data.get("articles", [])}

    def mark_article(self, data, article_id, now=None):
        if not article_id:
            return
        now = now or datetime.now(timezone.utc)
        self.prune(data, now)
        if not self.has_article(data, article_id):
            data.setdefault("articles", []).append({"id": str(article_id), "seen_at": now.isoformat()})
        data["updated_at"] = now.isoformat()

    def add(self, data, event, now=None):
        now = now or datetime.now(timezone.utc)
        self.prune(data, now)
        record = {
            "type": event.get("type"),
            "from": event.get("from"),
            "to": event.get("to"),
            "player": event.get("player"),
            "person": event.get("person"),
            "entity_type": event.get("entity_type"),
            "seen_at": now.isoformat(),
        }
        data.setdefault("events", []).append(record)
        data["updated_at"] = now.isoformat()

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
