import json
import re
from pathlib import Path

import requests
from .gemini_rate_limit import GeminiRateLimiter, GeminiTransientError


# These values are deliberately human-readable because they are also used in
# channel subscription configuration. Keep them stable once deployed.
CONTENT_TYPES = (
    "انتقال",
    "إعارة",
    "هدف",
    "نتيجة",
    "مباراة",
    "إصابة",
    "عودة من إصابة",
    "تجديد عقد",
    "تعيين مدرب",
    "إقالة مدرب",
    "اعتزال",
    "انتقال إداري",
    "استحواذ",
    "بيع أصول",
    "تصريح",
    "انضباط",
    "أخبار ناد",
    "أخرى",
)

_ALLOWED_ENTITIES = ("player", "club", "manager", "match")
_TRANSFER_TYPES = {"انتقال", "إعارة"}
_PLAYER_LED_TYPES = {"انتقال", "إعارة", "هدف", "إصابة", "عودة من إصابة", "تجديد عقد", "اعتزال", "انضباط"}


class GeminiNewsExtractor:
    """Classify one article into a safe, reusable four-field event identity.

    Gemini is a classifier, not an author. Its structured output is compared
    against the current week's event list before the source article is ever
    published. ``from`` means the club currently concerned by the news; ``to``
    is populated only for transfers and loans.
    """

    def __init__(self, api_key, timeout=30, model="gemini-3.6-flash", prompt_dir=None, rate_limiter=None):
        self.api_key = api_key
        self.timeout = timeout
        self.model = model
        self.prompt_dir = Path(prompt_dir) if prompt_dir else None
        self.rate_limiter = rate_limiter or GeminiRateLimiter(min_interval_seconds=0)
        self.last_failure_transient = False
        self.endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )

    def extract(self, item):
        self.last_failure_transient = False
        prompt = {
            "task": "Classify one football news article into one structured event. "
                    "Return null only when the article is not a meaningful football news item.",
            "classification_prompt": self._read_prompt("classify.txt"),
            "allowed_types": list(CONTENT_TYPES),
            "rules": [
                "Return JSON only and do not write commentary.",
                "type MUST be exactly one value from allowed_types.",
                "player is the full player name when a player is central to the news; otherwise null.",
                "person is the full original-language name of the player or manager central to the news; for player-led news it MUST equal player, and otherwise it is null.",
                "from is the club or national team currently concerned by the news. It is required for every event.",
                "to is ONLY used when type is انتقال or إعارة. For every other type it MUST be null.",
                "For انتقال and إعارة, from is the club the player leaves and to is the destination club.",
                "For هدف, from is the scorer's club or national team and player is the scorer.",
                "For نتيجة or مباراة, from is the main club or national team in the article; player is null unless one player is central.",
                "For injuries, renewals, discipline, retirement and statements, from is the player's current club or national team.",
                "For manager news, from is the club or national team involved and player is null.",
                "Never infer a player, club, destination, score or event from a headline alone when the article does not state it.",
                "Do not classify transfer rumours as confirmed انتقال unless the article clearly reports a completed or agreed move; otherwise use أخبار ناد.",
                "Normalize whitespace only and preserve names in their original language.",
            ],
            "output": {
                "type": "one allowed type",
                "from": "club or national-team name",
                "to": "destination club only for انتقال or إعارة; otherwise null",
                "player": "full player name or null",
                "person": "full original player or manager name, or null",
                "entity_type": "player|club|manager|match",
            },
            "article": {
                "title": item.get("title"),
                "summary": item.get("summary"),
                "source": item.get("source"),
                "url": item.get("url"),
            },
        }

        try:
            response = self.rate_limiter.post(
                requests.post,
                self.endpoint,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self.api_key,
                },
                json={
                    "contents": [{
                        "role": "user",
                        "parts": [{"text": json.dumps(prompt, ensure_ascii=False)}],
                    }],
                    "generationConfig": {
                        "temperature": 0,
                        "maxOutputTokens": 320,
                        "responseMimeType": "application/json",
                        "thinkingConfig": {"thinkingLevel": "minimal"},
                    },
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            raw = data["candidates"][0]["content"]["parts"][0]["text"]
            obj = json.loads(re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip())
        except GeminiTransientError as exc:
            self.last_failure_transient = True
            print(f"[news-gemini] temporary classification failure: {exc}")
            return None
        except Exception as exc:
            print(f"[news-gemini] classification failed: {exc}")
            return None

        if not isinstance(obj, dict):
            return None

        event_type = self._clean(obj.get("type"))
        frm = self._clean(obj.get("from"))
        to = self._clean(obj.get("to"))
        player = self._clean(obj.get("player"))
        person = self._clean(obj.get("person")) or player
        entity_type = self._clean(obj.get("entity_type")) or "club"

        if event_type not in CONTENT_TYPES or not frm or entity_type not in _ALLOWED_ENTITIES:
            return None
        if event_type in _TRANSFER_TYPES:
            if not to or not player:
                return None
        elif to:
            return None
        if event_type in _PLAYER_LED_TYPES and not player:
            return None
        if entity_type == "player" and not player:
            return None
        if entity_type == "manager" and not person:
            return None

        return {
            "type": event_type,
            "from": frm,
            "to": to if event_type in _TRANSFER_TYPES else None,
            "player": player,
            "person": person,
            "entity_type": entity_type,
        }

    @staticmethod
    def _supported(value, source_text):
        if not value:
            return False
        normalized_value = re.sub(r"[^\w\s]", " ", value.casefold())
        normalized_text = re.sub(r"[^\w\s]", " ", source_text.casefold())
        if re.search(r"\b" + r"\s+".join(re.escape(part) for part in normalized_value.split()) + r"\b", normalized_text):
            return True
        parts = [part for part in normalized_value.split() if len(part) > 2]
        return bool(parts) and all(re.search(r"\b" + re.escape(part) + r"\b", normalized_text) for part in parts)

    @classmethod
    def validate_event(cls, event, item):
        """Reject structured entities not supported by the source text."""
        if not isinstance(event, dict) or not isinstance(item, dict):
            return False
        source_text = " ".join(str(item.get(key) or "") for key in ("title", "summary", "content"))
        if not source_text.strip():
            return False
        for field in ("from", "player", "person"):
            value = event.get(field)
            if value and not cls._supported(value, source_text):
                return False
        if event.get("to") and not cls._supported(event["to"], source_text):
            return False
        if event.get("type") in _TRANSFER_TYPES:
            movement_words = r"\b(sign|signed|signing|join|joined|move|moves|transfer|loan|deal|agreement)\b"
            if not re.search(movement_words, source_text, re.I):
                return False
        return True

    def _read_prompt(self, name):
        if not self.prompt_dir:
            return ""
        try:
            return (self.prompt_dir / name).read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    @staticmethod
    def _clean(value):
        if not isinstance(value, str):
            return None
        value = re.sub(r"\s+", " ", value).strip()
        return value or None
