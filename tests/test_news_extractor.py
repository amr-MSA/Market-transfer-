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
                        "person": "Ezri Konsa",
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
        "person": "Ezri Konsa",
        "entity_type": "player",
    }


def test_validate_event_rejects_hallucinated_player():
    item = {"title": "Arsenal agree deal to sign Ezri Konsa", "summary": "Aston Villa defender Ezri Konsa is expected to move."}
    event = {"type": "انتقال", "from": "Aston Villa", "to": "Arsenal", "player": "Player B"}
    assert GeminiNewsExtractor.validate_event(event, item) is False


def test_validate_event_accepts_supported_transfer():
    item = {"title": "Arsenal agree deal to sign Ezri Konsa", "summary": "Aston Villa defender Ezri Konsa is expected to move to Arsenal."}
    event = {"type": "انتقال", "from": "Aston Villa", "to": "Arsenal", "player": "Ezri Konsa"}
    assert GeminiNewsExtractor.validate_event(event, item) is True


def test_validate_event_rejects_transfer_without_movement_context():
    item = {"title": "Ezri Konsa discusses his Arsenal contract", "summary": "The player spoke about football."}
    event = {"type": "انتقال", "from": "Aston Villa", "to": "Arsenal", "player": "Ezri Konsa"}
    assert GeminiNewsExtractor.validate_event(event, item) is False


def test_news_extractor_keeps_manager_name_for_safe_image_matching(monkeypatch):
    class ManagerResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "candidates": [{
                    "content": {
                        "parts": [{"text": json.dumps({
                            "type": "تعيين مدرب",
                            "from": "Tottenham Hotspur",
                            "to": None,
                            "player": None,
                            "person": "Thomas Frank",
                            "entity_type": "manager",
                        })}]
                    }
                }]
            }

    monkeypatch.setattr("bot.news_extractor.requests.post", lambda *args, **kwargs: ManagerResponse())
    event = GeminiNewsExtractor("KEY").extract({
        "title": "Tottenham appoint Thomas Frank as head coach",
        "summary": "Thomas Frank joins Tottenham Hotspur as their new head coach.",
        "source": "BBC",
        "url": "https://example.test/article",
    })
    assert event["person"] == "Thomas Frank"
    assert event["entity_type"] == "manager"
