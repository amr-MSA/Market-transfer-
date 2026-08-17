import json
import re
from difflib import SequenceMatcher


class EventDeduplicator:
    """Detect the same football event across different sources.

    Stage 1: cheap local candidate matching.
    Stage 2: Gemini semantic comparison for ambiguous candidates.

    The class does not decide publication policy; it only groups related
    articles into event clusters.
    """

    STOPWORDS = {
        "the", "a", "an", "to", "of", "for", "and", "in", "on", "with",
        "from", "is", "are", "has", "have", "will", "this", "that",
        "football", "soccer", "news", "report", "reports", "latest",
        "breaking", "confirmed", "official", "set", "close", "could",
        "would", "says", "say",
    }

    def __init__(self, state, gemini=None, threshold=0.82, max_candidates=8):
        self.state = state
        self.gemini = gemini
        self.threshold = threshold
        self.max_candidates = max_candidates

    @classmethod
    def normalize(cls, text):
        text = (text or "").lower()
        text = re.sub(r"https?://\S+", " ", text)
        text = re.sub(r"[^a-z0-9\u0600-\u06ff\s]", " ", text)
        words = [
            w for w in text.split()
            if len(w) > 1 and w not in cls.STOPWORDS
        ]
        return " ".join(words)

    @classmethod
    def similarity(cls, a, b):
        na = cls.normalize(a)
        nb = cls.normalize(b)

        if not na or not nb:
            return 0.0

        seq = SequenceMatcher(None, na, nb).ratio()

        sa = set(na.split())
        sb = set(nb.split())
        union = sa | sb
        jaccard = len(sa & sb) / len(union) if union else 0.0

        return max(seq, jaccard)

    def local_candidates(self, item, existing):
        title = item.get("title", "")
        scored = []

        for event in existing:
            representative = event.get("representative", {})
            other_title = representative.get("title", "")
            score = self.similarity(title, other_title)

            if score >= 0.45:
                scored.append((score, event))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[: self.max_candidates]

    def find_or_create(self, item, events):
        candidates = self.local_candidates(item, events)

        if candidates:
            best_score, best = candidates[0]

            # Very strong lexical match: no Gemini call required.
            if best_score >= self.threshold:
                return best, "local"

            # Ambiguous: let Gemini compare the small candidate set.
            if self.gemini:
                result = self.gemini.compare_event(
                    item,
                    [event for _, event in candidates],
                )

                if result and result.get("same_event"):
                    event_id = result.get("event_id")
                    for event in candidates:
                        if event.get("event_id") == event_id:
                            return event, "gemini"

        # New event.
        event_id = self._make_event_id(item, len(events) + 1)

        event = {
            "event_id": event_id,
            "created_at": item.get("published_at"),
            "representative": {
                "title": item.get("title", ""),
                "summary": item.get("summary", ""),
                "url": item.get("url", ""),
                "source": item.get("source", ""),
            },
            "sources": [],
            "updates": [],
        }

        events.append(event)
        return event, "new"

    @staticmethod
    def _make_event_id(item, sequence):
        category = item.get("category", "FOOTBALL_NEWS").lower()
        title = EventDeduplicator.normalize(item.get("title", ""))
        words = title.split()[:8]
        slug = "-".join(words) or f"item-{sequence}"
        return f"{category}:{slug}"

    @staticmethod
    def attach(event, item):
        source_record = {
            "source": item.get("source"),
            "url": item.get("url"),
            "published_at": item.get("published_at"),
        }

        urls = {
            x.get("url")
            for x in event.setdefault("sources", [])
        }

        if source_record["url"] not in urls:
            event["sources"].append(source_record)

        event.setdefault("updates", []).append({
            "title": item.get("title"),
            "source": item.get("source"),
            "url": item.get("url"),
            "category": item.get("category"),
            "published_at": item.get("published_at"),
        })

        return event


class GeminiEventComparer:
    """Small Gemini adapter used only for ambiguous duplicate detection."""

    def __init__(self, api_key, model="gemini-2.5-flash", timeout=30):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def compare_event(self, item, candidates):
        if not self.api_key:
            return None

        try:
            import requests

            candidate_payload = []
            for event in candidates:
                rep = event.get("representative", {})
                candidate_payload.append({
                    "event_id": event.get("event_id"),
                    "title": rep.get("title"),
                    "summary": rep.get("summary"),
                    "source": rep.get("source"),
                })

            prompt = {
                "task": "Determine whether the new football article reports the same real-world event as one of the existing events.",
                "new_article": {
                    "title": item.get("title"),
                    "summary": item.get("summary"),
                    "source": item.get("source"),
                    "category": item.get("category"),
                },
                "existing_events": candidate_payload,
                "rules": [
                    "same_event=true only when they describe the same underlying event, not merely the same club or player",
                    "rumour, negotiation, agreement and official completion are different stages but may belong to the same transfer event",
                    "return the existing event_id when same_event=true",
                    "return null event_id when none matches",
                ],
                "output_schema": {
                    "same_event": "boolean",
                    "event_id": "string|null",
                    "reason": "short string",
                },
            }

            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.model}:generateContent"
                f"?key={self.api_key}"
            )

            response = requests.post(
                url,
                json={
                    "contents": [{
                        "parts": [{
                            "text": json.dumps(
                                prompt,
                                ensure_ascii=False,
                            )
                        }]
                    }],
                    "generationConfig": {
                        "temperature": 0,
                        "responseMimeType": "application/json",
                    },
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()

            text = (
                data["candidates"][0]["content"]["parts"][0]["text"]
            )
            result = json.loads(text)

            if not isinstance(result, dict):
                return None

            return result

        except Exception as exc:
            print(f"[gemini-dedup] unavailable: {exc}")
            return None
