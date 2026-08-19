import json
import re

import requests


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

    def __init__(self, api_key, timeout=30, model="gemini-2.5-flash"):
        self.api_key = api_key
        self.timeout = timeout
        self.model = model
        self.endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )

    def extract(self, item):
        prompt = {
            "task": "Classify one football news article into one structured event. "
                    "Return null only when the article is not a meaningful football news item.",
            "allowed_types": list(CONTENT_TYPES),
            "rules": [
                "Return JSON only and do not write commentary.",
                "type MUST be exactly one value from allowed_types.",
                "player is the full player name when a player is central to the news; otherwise null.",
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
            response = requests.post(
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
        except Exception as exc:
            print(f"[news-gemini] classification failed: {exc}")
            return None

        if not isinstance(obj, dict):
            return None

        event_type = self._clean(obj.get("type"))
        frm = self._clean(obj.get("from"))
        to = self._clean(obj.get("to"))
        player = self._clean(obj.get("player"))
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

        return {
            "type": event_type,
            "from": frm,
            "to": to if event_type in _TRANSFER_TYPES else None,
            "player": player,
            "entity_type": entity_type,
        }

    @staticmethod
    def _clean(value):
        if not isinstance(value, str):
            return None
        value = re.sub(r"\s+", " ", value).strip()
        return value or None
