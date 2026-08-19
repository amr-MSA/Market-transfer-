import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class NewsState:
    """Persistent delivery state for structured football-news events.

    Each event is keyed by a stable identifier supplied by the caller. An event
    is considered published only after every target channel reports success.
    Failed deliveries remain retryable on the next run.
    """

    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return {"updated_at": None, "published": {}}
        try:
            with self.path.open(encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError, TypeError):
            return {"updated_at": None, "published": {}}

        if not isinstance(data, dict) or not isinstance(data.get("published", {}), dict):
            return {"updated_at": None, "published": {}}
        data.setdefault("updated_at", None)
        return data

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def mark_result(self, data, event_id, results, event=None, now=None):
        """Merge channel results and mark an event published on full success."""
        if not isinstance(data, dict):
            raise TypeError("news state must be a dictionary")
        published = data.setdefault("published", {})
        record = published.setdefault(event_id, {})
        if event:
            record.update(dict(event))

        delivery = record.setdefault("delivery", {})
        for result in results or []:
            channel_id = str(result.get("id"))
            delivery[channel_id] = "SENT" if result.get("ok") else "FAILED"

        timestamp = now.isoformat() if hasattr(now, "isoformat") else (now or self._now())
        record.setdefault("published_at", None)
        if results and all(result.get("ok") for result in results):
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
