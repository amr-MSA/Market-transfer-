"""Two-stage Gemini editorial layer.

Stage one remains the structured classifier in ``news_extractor.py``. This
module is stage two: it translates names and writes a short Arabic newsroom
copy from facts only. The final Telegram markup is still owned by formatting.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import requests


_SECTION_PROMPTS = {
    "انتقال": "transfer.txt",
    "إعارة": "loan.txt",
    "هدف": "goal.txt",
    "نتيجة": "result.txt",
    "مباراة": "match.txt",
    "إصابة": "injury.txt",
    "عودة من إصابة": "return_injury.txt",
    "تجديد عقد": "renewal.txt",
    "تعيين مدرب": "manager.txt",
    "إقالة مدرب": "manager.txt",
    "تصريح": "statement.txt",
    "أخبار ناد": "club_news.txt",
    "انضباط": "disciplinary.txt",
    "أخرى": "other.txt",
}

_ALLOWED_STATUSES = {"رسمي", "Here We Go", "خبر صحفي", "غير محدد"}


class GeminiEditorialWriter:
    def __init__(self, api_key, prompt_dir, timeout=30, model="gemini-3.6-flash"):
        self.api_key = api_key
        self.prompt_dir = Path(prompt_dir)
        self.timeout = timeout
        self.model = model
        self.endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )

    def write(self, item, event, status=None):
        """Return a safe editorial object or ``None`` when Gemini fails."""
        section = event.get("type") or event.get("section") or "أخرى"
        section = section if section in _SECTION_PROMPTS else "أخرى"
        status = status if status in _ALLOWED_STATUSES else "غير محدد"
        rules = self._read("editorial_rules.txt")
        section_rules = self._read(_SECTION_PROMPTS[section])
        payload = {
            "task": "Translate and write a short Arabic football news card.",
            "global_editorial_rules": rules,
            "section_rules": section_rules,
            "required_output": {
                "headline": "Arabic headline, 8-14 words",
                "lead": "One concise Arabic sentence",
                "detail": "Optional second sentence or null; do not use it for transfer captions",
                "comment_ar": "One short editorial observation, maximum 140 characters, or null",
                "player_ar": "Arabic player name or null",
                "player_original": "Original player name or null",
                "from_ar": "Arabic source club or null",
                "from_original": "Original source club or null",
                "to_ar": "Arabic destination club or null",
                "to_original": "Original destination club or null",
                "club_ar": "Arabic main club or null",
                "club_original": "Original main club or null",
                "quote_ar": "Faithful Arabic translation of quote or null",
            },
            "constraints": [
                "Return JSON only.",
                "Use only facts from the article and structured event.",
                "Do not add emojis, HTML, markdown, URLs, source names or hashtags.",
                "Keep the result suitable for a compact Telegram caption of 3-5 short lines.",
                "For transfer and loan events, comment_ar must be one short useful observation based only on the source; never write a paragraph.",
                "Use Arabic names followed by the original name in parentheses on first mention.",
                "Never invent a quote, score, fee, date, injury duration or transfer status.",
                f"The event section is exactly: {section}.",
                f"The event status is exactly: {status}.",
            ],
            "structured_event": event,
            "article": {
                "title": item.get("title"),
                "summary": item.get("summary"),
                "source": item.get("source"),
            },
        }
        obj = self._request(payload)
        return self._validate(obj, section, status)

    def _read(self, name):
        try:
            return (self.prompt_dir / name).read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _request(self, payload):
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
                        "parts": [{"text": json.dumps(payload, ensure_ascii=False)}],
                    }],
                    "generationConfig": {
                        "temperature": 0.2,
                        "maxOutputTokens": 420,
                        "responseMimeType": "application/json",
                        "thinkingConfig": {"thinkingLevel": "minimal"},
                    },
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            raw = data["candidates"][0]["content"]["parts"][0]["text"]
            raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
            return json.loads(raw)
        except Exception as exc:
            print(f"[news-editorial] writing failed: {exc}")
            return None

    @staticmethod
    def _clean(value):
        if not isinstance(value, str):
            return None
        value = re.sub(r"\s+", " ", value).strip()
        return value or None

    def _validate(self, obj, section, status):
        if not isinstance(obj, dict):
            return None
        headline = self._clean(obj.get("headline"))
        lead = self._clean(obj.get("lead"))
        detail = self._clean(obj.get("detail"))
        comment = self._clean(obj.get("comment_ar"))
        if not headline or not lead:
            return None
        if len(headline) > 180 or len(lead) > 360 or (detail and len(detail) > 360) or (comment and len(comment) > 140):
            return None
        return {
            "section": section,
            "status": status,
            "headline": headline,
            "lead": lead,
            "detail": detail,
            "comment_ar": comment,
            "player_ar": self._clean(obj.get("player_ar")),
            "player_original": self._clean(obj.get("player_original")),
            "from_ar": self._clean(obj.get("from_ar")),
            "from_original": self._clean(obj.get("from_original")),
            "to_ar": self._clean(obj.get("to_ar")),
            "to_original": self._clean(obj.get("to_original")),
            "club_ar": self._clean(obj.get("club_ar")),
            "club_original": self._clean(obj.get("club_original")),
            "quote_ar": self._clean(obj.get("quote_ar")),
        }
