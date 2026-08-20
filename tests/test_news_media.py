from bot.news_sources import FootballNewsSource
from bot.publisher import TelegramPublisher


def test_rss_image_is_extracted_from_media_content():
    entry = {
        "media_content": [{"url": "https://cdn.example.test/konsa.jpg"}],
    }
    assert FootballNewsSource._image_url(entry) == "https://cdn.example.test/konsa.jpg"


def test_rss_image_is_extracted_from_summary_html():
    entry = {}
    summary = '<p><img src="https://cdn.example.test/article.jpg" /></p>'
    assert FootballNewsSource._image_url(entry, summary) == "https://cdn.example.test/article.jpg"


def test_publisher_uses_photo_when_image_is_available(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True, "result": {"message_id": 1}}

    def fake_post(url, json, timeout):
        calls.append((url, json, timeout))
        return Response()

    monkeypatch.setattr("bot.publisher.requests.post", fake_post)
    publisher = TelegramPublisher(
        "TOKEN",
        [{"id": "-1001", "name": "Test", "enabled": True}],
        send_delay_seconds=0,
    )
    results = publisher.send(
        "📰 <b>خبر</b>",
        image_url="https://cdn.example.test/article.jpg",
    )

    assert results[0]["ok"] is True
    assert calls[0][0].endswith("/sendPhoto")
    assert calls[0][1]["photo"] == "https://cdn.example.test/article.jpg"
    assert calls[0][1]["caption"] == "📰 <b>خبر</b>"
