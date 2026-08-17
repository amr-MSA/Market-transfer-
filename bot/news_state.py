import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


class NewsState:
    """Persistent deduplication and per-channel delivery state for RSS news."""

    def __init__(self, path, retention_days=3):
        self.path = Path(path)
        self.retention_days = retention_days

    def load(self):
        if not self.path.exists():
            return {"published": {}, "events": []}

        try:
            with self.path.open(encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                return {"published": {}, "events": []}

            published = data.get("published", {})
            if not isinstance(published, dict):
                published = {}

            events = data.get("events", [])
            if not isinstance(events, list):
                events = []

            return {"published": published, "events": events}
        except (OSError, ValueError):
            return {"published": {}, "events": []}

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")

        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")

        os.replace(tmp, self.path)

    def prune(self, data):
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        kept = {}

        for key, value in data.get("published", {}).items():
            if isinstance(value, str):
                marker = value
            elif isinstance(value, dict):
                marker = value.get("published_at")
            else:
                continue

            try:
                when = datetime.fromisoformat(
                    marker.replace("Z", "+00:00")
                )
            except (AttributeError, ValueError):
                continue

            if when >= cutoff:
                kept[key] = value

        data["published"] = kept

        # Keep event clusters for the same retention window.
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        events = []
        for event in data.get("events", []):
            marker = event.get("created_at")
            if not marker:
                events.append(event)
                continue
            try:
                when = datetime.fromisoformat(marker.replace("Z", "+00:00"))
            except (AttributeError, ValueError):
                continue
            if when >= cutoff:
                events.append(event)
        data["events"] = events
        return data

    def get(self, data, item_id):
        value = data.setdefault("published", {}).get(item_id)

        # Backward compatibility with the first simple state format.
        if isinstance(value, str):
            value = {
                "published_at": value,
                "delivery": {},
            }
            data["published"][item_id] = value

        if not isinstance(value, dict):
            value = {
                "published_at": None,
                "delivery": {},
            }
            data["published"][item_id] = value

        value.setdefault("delivery", {})
        return value

    def was_fully_published(self, data, item_id, channel_ids):
        item = data.get("published", {}).get(item_id)
        if not isinstance(item, dict):
            return False

        delivery = item.get("delivery", {})
        return all(delivery.get(cid) == "SENT" for cid in channel_ids)

    def mark_result(self, data, item_id, results, when=None):
        item = self.get(data, item_id)

        if item.get("published_at") is None:
            item["published_at"] = (
                when or datetime.now(timezone.utc)
            ).isoformat()

        delivery = item.setdefault("delivery", {})

        for result in results:
            delivery[str(result["id"])] = (
                "SENT" if result["ok"] else "FAILED"
            )

    def latest_publish_time(self, data):
        latest = None

        for item in data.get("published", {}).values():
            if not isinstance(item, dict):
                continue

            marker = item.get("published_at")
            if not marker:
                continue

            try:
                when = datetime.fromisoformat(
                    marker.replace("Z", "+00:00")
                )
            except (AttributeError, ValueError):
                continue

            if latest is None or when > latest:
                latest = when

        return latest
