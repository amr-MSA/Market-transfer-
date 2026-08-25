import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .news_dedup import NewsDedupStore


class NewsState:
    """Persistent delivery state for structured football-news events.

    Each event is keyed by a stable identifier supplied by the caller. An event
    is considered published only after every target channel reports success.
    Failed deliveries remain retryable on the next run.
    """

    def __init__(self, path, retention_days=7):
        self.path = Path(path)
        self.dedup = NewsDedupStore(path, retention_days)

    def load(self):
        if not self.path.exists():
            return {"week_start": None, "updated_at": None, "events": [], "articles": [], "published": {}}
        try:
            with self.path.open(encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError, TypeError):
            return {"week_start": None, "updated_at": None, "events": [], "articles": [], "published": {}}

        if not isinstance(data, dict) or not isinstance(data.get("published", {}), dict):
            return {"week_start": None, "updated_at": None, "events": [], "articles": [], "published": {}}
        data.setdefault("week_start", None)
        data.setdefault("updated_at", None)
        data.setdefault("events", [])
        data.setdefault("articles", [])
        return data

    def prune(self, data, now=None):
        return self.dedup.prune(data, now)

    def contains(self, data, event):
        return self.dedup.contains(data, event)

    @staticmethod
    def has_article(data, article_id):
        return NewsDedupStore.has_article(data, article_id)

    def mark_article(self, data, article_id, now=None):
        return self.dedup.mark_article(data, article_id, now)

    def add(self, data, event, now=None):
        return self.dedup.add(data, event, now)

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def event_id(event):
        values = [str(event.get(field) or "").casefold().strip() for field in ("type", "from", "to", "player", "person")]
        return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def get_record(data, event_id):
        return data.setdefault("published", {}).get(event_id)

    @staticmethod
    def find_by_article(data, article_id):
        article_id = str(article_id or "")
        for record in data.setdefault("published", {}).values():
            if str(record.get("article_id", "")) == article_id:
                return record
        return None

    @staticmethod
    def pending_channels(record, channels):
        delivery = (record or {}).get("delivery", {})
        return [channel for channel in channels if delivery.get(str(channel["id"])) != "SENT"]

    def mark_result(self, data, event_id, results, event=None, now=None):
        """Merge channel results; successful channels remain permanently SENT."""
        if not isinstance(data, dict):
            raise TypeError("news state must be a dictionary")
        published = data.setdefault("published", {})
        record = published.setdefault(event_id, {})
        if event:
            record.update(dict(event))
        record["event_id"] = event_id

        delivery = record.setdefault("delivery", {})
        for result in results or []:
            channel_id = str(result.get("id"))
            # Never downgrade a previously successful channel because a later
            # retry or Telegram response is incomplete.
            if result.get("ok"):
                delivery[channel_id] = "SENT"
            elif delivery.get(channel_id) != "SENT":
                delivery[channel_id] = "FAILED"

        timestamp = now.isoformat() if hasattr(now, "isoformat") else (now or self._now())
        record.setdefault("published_at", None)
        target_ids = set(record.get("target_channel_ids", []))
        sent_ids = {channel_id for channel_id, state in delivery.items() if state == "SENT"}
        if (target_ids and target_ids.issubset(sent_ids)) or (not target_ids and results and all(result.get("ok") for result in results)):
            record["published_at"] = timestamp
        record["updated_at"] = timestamp
        data["updated_at"] = timestamp
        return record

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
