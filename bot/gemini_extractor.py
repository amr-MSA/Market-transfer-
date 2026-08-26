import json
import re
import requests
from .gemini_rate_limit import GeminiRateLimiter, GeminiTransientError

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

_SYSTEM_PROMPT = (
    "You extract structured data from a single football (soccer) transfer "
    "news post. The post is confirmed to contain the exact phrase "
    "'here we go', which is Fabrizio Romano's signal that a transfer deal "
    "is agreed (not necessarily officially announced by the club yet).\n\n"
    "Return ONLY a JSON object, no markdown fences, no extra text, in "
    "exactly this shape:\n"
    '{"player": string or null, "to_club": string or null, '
    '"from_club": string or null}\n\n'
    "Rules:\n"
    "- player: the footballer's full name as written in the post.\n"
    "- to_club: the club the player is joining.\n"
    "- from_club: the club the player is leaving, or null if not stated.\n"
    "- If the post is not actually about a single specific player joining "
    "a single specific club (e.g. it's a rumor with no 'here we go', a "
    "managerial move, an injury update, a podcast promo, or covers "
    "multiple unrelated deals), return "
    '{"player": null, "to_club": null, "from_club": null}.\n'
    "- Never invent a name that is not present in the text.\n"
    "- Output raw JSON only."
)


class GeminiExtractor:
    """Fallback extractor used only when the regex parser (bot/parser.py)
    fails to confidently parse a 'here we go' post. Kept as a fallback
    rather than the primary path to stay inside the free tier and to avoid
    paying an API call for the majority of posts the regex already handles.
    """

    def __init__(self, api_key, timeout=20, model="gemini-3.6-flash", rate_limiter=None):
        self.api_key = api_key
        self.timeout = timeout
        self.model = model
        self.rate_limiter = rate_limiter or GeminiRateLimiter(min_interval_seconds=0)

    def extract(self, text):
        url = _ENDPOINT.format(model=self.model)
        payload = {
            "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 200,
                "responseMimeType": "application/json",
                # This is a simple, single-shot extraction task, not
                # multi-step reasoning — "minimal" thinking keeps latency
                # and output-token usage (billed) as low as possible.
                "thinkingConfig": {"thinkingLevel": "minimal"},
            },
        }
        try:
            r = self.rate_limiter.post(
                requests.post,
                url,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self.api_key,
                },
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, GeminiTransientError):
            # Network/API failure must never crash the run — just means no
            # extraction happened this cycle; the post is retried next poll
            # since state is only saved for posts we could parse.
            return {"player": None, "to_club": None, "from_club": None}

        raw = self._extract_text(data)
        parsed = self._safe_json(raw)
        if not parsed:
            return {"player": None, "to_club": None, "from_club": None}

        return {
            "player": self._clean(parsed.get("player")),
            "to_club": self._clean(parsed.get("to_club")),
            "from_club": self._clean(parsed.get("from_club")),
        }

    @staticmethod
    def _extract_text(data):
        try:
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError):
            return ""

    @staticmethod
    def _safe_json(raw):
        if not raw:
            return None
        # Defensive: strip markdown fences if the model adds them despite
        # responseMimeType being set to application/json.
        cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
        try:
            obj = json.loads(cleaned)
        except json.JSONDecodeError:
            return None
        return obj if isinstance(obj, dict) else None

    @staticmethod
    def _clean(value):
        if not isinstance(value, str):
            return None
        value = value.strip()
        return value or None
