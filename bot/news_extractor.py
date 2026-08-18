import json
import re
import requests


_ALLOWED_TYPES = (
    "انتقال",
    "إعارة",
    "تجديد عقد",
    "تعيين مدرب",
    "إقالة مدرب",
    "إصابة",
    "عودة من إصابة",
    "اعتزال",
    "انتقال إداري",
    "استحواذ",
    "بيع أصول",
)

_ALLOWED_ENTITIES = ("player", "club", "manager")


class GeminiNewsExtractor:
    """Strict classifier/extractor for news deduplication.

    Gemini does not write prose here. It returns only the normalized event
    fields used by the seven-day duplicate cache.
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
            "task": "Extract one structured football event from the supplied article. "
                    "If it is not a meaningful football event from the allowed list, return null.",
            "allowed_entity_type": list(_ALLOWED_ENTITIES),
            "allowed_type": list(_ALLOWED_TYPES),
            "rules": [
                "Return JSON only.",
                "type MUST be exactly one of the allowed type values.",
                "entity_type MUST be exactly player, club, or manager.",
                "For player events, player is the full player name. For club/manager events, player is null.",
                "For انتقال and إعارة: from is the club the player leaves and to is the destination club.",
                "For non-transfer player news such as إصابة or تجديد عقد: from is the player's club and to is null.",
                "Do not infer a transfer merely because two clubs are mentioned.",
                "Do not use a match, goal, training photo, quote, or routine social post as a transfer.",
                "For استحواذ: entity_type=club, from is the acquiring party and to is the acquired club.",
                "For بيع أصول: entity_type=club, from is the seller/previous owner and to is the club/asset buyer.",
                "Never invent a name, club, or relationship absent from the article.",
                "If a required field cannot be established safely, return null.",
                "Normalize whitespace only; do not translate names.",
            ],
            "output": {
                "entity_type": "player|club|manager",
                "type": "one allowed value",
                "player": "string|null",
                "from": "string|null",
                "to": "string|null",
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
                        "parts": [{
                            "text": json.dumps(prompt, ensure_ascii=False)
                        }]
                    }],
                    "generationConfig": {
                        "temperature": 0,
                        "maxOutputTokens": 300,
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
            print(f"[news-gemini] extraction failed: {exc}")
            return None

        if not isinstance(obj, dict):
            return None

        entity_type = obj.get("entity_type")
        event_type = obj.get("type")
        if entity_type not in _ALLOWED_ENTITIES or event_type not in _ALLOWED_TYPES:
            return None

        player = self._clean(obj.get("player"))
        frm = self._clean(obj.get("from"))
        to = self._clean(obj.get("to"))

        if entity_type == "player" and not player:
            return None
        if entity_type in {"club", "manager"}:
            player = None

        if event_type in {"انتقال", "إعارة"}:
            if not frm or not to:
                return None
        else:
            to = None
            if not frm:
                return None

        return {
            "entity_type": entity_type,
            "type": event_type,
            "player": player,
            "from": frm,
            "to": to,
        }

    @staticmethod
    def _clean(value):
        if not isinstance(value, str):
            return None
        value = re.sub(r"\s+", " ", value).strip()
        return value or None
