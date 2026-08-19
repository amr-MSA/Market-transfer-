import hashlib
import re
from difflib import SequenceMatcher
from datetime import datetime, timezone


class EventDeduplicator:
    """Finds semantically similar structured news events without external calls."""

    _NOISE = re.compile(r"\b(?:breaking|exclusive|update|confirmed|latest)\b", re.IGNORECASE)
    _PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
    _SPACES = re.compile(r"\s+")

    def __init__(self, events=None, threshold=0.88):
        self.events = events if events is not None else []
        self.threshold = threshold

    @classmethod
    def normalize(cls, value):
        if value is None:
            return ""
        text = cls._NOISE.sub(" ", str(value).casefold())
        text = cls._PUNCTUATION.sub(" ", text)
        return cls._SPACES.sub(" ", text).strip()

    @classmethod
    def similarity(cls, left, right):
        a = cls.normalize(left)
        b = cls.normalize(right)
        if not a or not b:
            return 0.0
        return SequenceMatcher(None, a, b).ratio()

    @classmethod
    def _event_id(cls, item):
        basis = "|".join(
            cls.normalize(item.get(field))
            for field in ("category", "title", "player", "from", "to")
        )
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:20]

    def find_or_create(self, item, events=None):
        records = self.events if events is None else events
        title = item.get("title", "")
        category = item.get("category")
        for event in records:
            if category and event.get("category") != category:
                continue
            if self.similarity(event.get("title", ""), title) >= self.threshold:
                return event, "duplicate"

        event = dict(item)
        event.setdefault("event_id", self._event_id(event))
        event.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        records.append(event)
        return event, "new"
