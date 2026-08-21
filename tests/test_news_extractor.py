import json

from bot.news_extractor import GeminiNewsExtractor


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "candidates": [{
                "content": {
                    "parts": [{"text": json.dumps({
                        "type": "انتقال",
                        "from": "Aston Villa",
                        "to": "Arsenal",
                        "player": "Ezri Konsa",
                        "entity_type": "player",
                    })}]
                }
            }]
        }


def test_news_extractor_accepts_structured_transfer(monkeypatch):
    monkeypatch.setattr("bot.news_extractor.requests.post", lambda *args, **kwargs: _Response())
    extractor = GeminiNewsExtractor("KEY")
    event = extractor.extract({
        "title": "Arsenal agree deal",
        "summary": "Konsa will move from Aston Villa to Arsenal.",
        "source": "BBC",
        "url": "https://example.test/article",
    })
    assert event == {
        "type": "انتقال",
        "from": "Aston Villa",
        "to": "Arsenal",
        "player": "Ezri Konsa",
        "entity_type": "player",
    }
