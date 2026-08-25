from bot.news_sources import FootballNewsSource
from bot.fabrizio import FabrizioSource
from bot.media import NewsImageSelector
from bot.publisher import TelegramPublisher
from bot.formatting import football_news_message
from bot.main import _resolve_media
from bot.media_library import MediaLibrary
from bot.identity_cards import IdentityCardRegistry


def test_rss_image_is_extracted_from_media_content():
    entry = {
        "media_content": [{"url": "https://cdn.example.test/konsa.jpg"}],
    }
    assert FootballNewsSource._image_url(entry) == "https://cdn.example.test/konsa.jpg"


def test_rss_image_is_extracted_from_summary_html():
    entry = {}
    summary = '<p><img src="https://cdn.example.test/article.jpg" /></p>'
    assert FootballNewsSource._image_url(entry, summary) == "https://cdn.example.test/article.jpg"


def test_fabrizio_image_is_extracted_from_telegram_widget_style():
    style = "background-image:url('https://cdn.telegram.org/media.jpg')"
    assert FabrizioSource._background_image_url(style) == "https://cdn.telegram.org/media.jpg"


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


def test_selector_keeps_a_source_image_only_when_quality_is_acceptable(monkeypatch):
    selector = NewsImageSelector()
    monkeypatch.setattr(selector, "_is_usable_image", lambda url: url == "https://source.test/good.jpg")
    monkeypatch.setattr(selector, "_wikimedia_media", lambda person: {"url": "https://commons.test/fallback.jpg"})

    media = selector.select("https://source.test/good.jpg", "Ezri Konsa", "player")

    assert media == {"url": "https://source.test/good.jpg", "source": "source"}


def test_selector_uses_wikimedia_only_after_source_image_fails_quality_check(monkeypatch):
    selector = NewsImageSelector()
    fallback = {
        "url": "https://commons.test/ezri.jpg",
        "source": "wikimedia",
        "credit_name": "Photographer",
        "credit_license": "CC BY-SA 4.0",
        "credit_url": "https://commons.test/file",
    }
    monkeypatch.setattr(selector, "_is_usable_image", lambda url: False)
    monkeypatch.setattr(selector, "_wikimedia_media", lambda person: fallback)

    assert selector.select("https://source.test/tiny.jpg", "Ezri Konsa", "player") == fallback


def test_selector_never_uses_wikimedia_for_an_unnamed_or_non_person_event(monkeypatch):
    selector = NewsImageSelector()
    monkeypatch.setattr(selector, "_is_usable_image", lambda url: False)
    monkeypatch.setattr(selector, "_wikimedia_media", lambda person: (_ for _ in ()).throw(AssertionError("must not search")))

    assert selector.select(None, None, "club") is None
    assert selector.select("https://source.test/tiny.jpg", "Arsenal", "club") is None


def test_selector_requires_unambiguous_football_wikidata_identity(monkeypatch):
    selector = NewsImageSelector()
    monkeypatch.setattr(selector, "_get_json", lambda endpoint, params: {
        "search": [
            {"id": "Q1", "label": "Alex Smith", "description": "English footballer"},
            {"id": "Q2", "label": "Alex Smith", "description": "Scottish football manager"},
        ]
    })

    assert selector._wikidata_entity_id("Alex Smith") is None


def test_selector_returns_commons_thumbnail_with_attribution(monkeypatch):
    selector = NewsImageSelector()
    monkeypatch.setattr(selector, "_is_usable_image", lambda url: True)
    monkeypatch.setattr(selector, "_get_json", lambda endpoint, params: {
        "query": {"pages": {"7": {
            "imageinfo": [{
                "thumburl": "https://upload.wikimedia.org/thumb.jpg",
                "descriptionurl": "https://commons.wikimedia.org/wiki/File:Portrait.jpg",
                "extmetadata": {
                    "Attribution": {"value": "Jane Photographer"},
                    "LicenseShortName": {"value": "CC BY-SA 4.0"},
                },
            }]
        }}}
    })

    media = selector._commons_file_media("Portrait.jpg")

    assert media["source"] == "wikimedia"
    assert media["url"] == "https://upload.wikimedia.org/thumb.jpg"
    assert media["credit_name"] == "Jane Photographer"
    assert media["credit_license"] == "CC BY-SA 4.0"


def test_wikimedia_attribution_is_shown_in_the_caption():
    text = football_news_message(
        {"title": "خبر", "source": "BBC", "url": "https://example.test/article"},
        media={
            "source": "wikimedia",
            "credit_name": "Jane Photographer",
            "credit_license": "CC BY-SA 4.0",
            "credit_url": "https://commons.wikimedia.org/wiki/File:Portrait.jpg",
        },
    )

    assert "📷" in text
    assert "Jane Photographer" in text
    assert "CC BY-SA 4.0" in text


def test_automatic_archive_reports_ambiguous_identity_without_archiving(tmp_path):
    class Selector:
        def select(self, *args):
            return {"url": "https://commons.example/alex.jpg", "source": "wikimedia", "credit_license": "CC BY-SA 4.0"}

    class Source:
        def candidates(self, *args, **kwargs):
            return [
                {"identity_key": "wikidata:Q1", "canonical_name": "Alex Silva"},
                {"identity_key": "wikidata:Q2", "canonical_name": "Alex Silva"},
            ]

    class Archive:
        enabled = True

        def archive(self, *args):
            raise AssertionError("must not archive an ambiguous person")

    registry = IdentityCardRegistry(tmp_path / "identity_cards.json")
    library = MediaLibrary(tmp_path / "media_library.json")
    notices = []

    media, archived, identity_updated = _resolve_media(
        Selector(), library, library.load(), Archive(), "Alex Silva", "player", "https://example.test/article",
        registry, registry.load(), None, Source(),
        ambiguity_notifier=lambda *args: notices.append(args), club="Arsenal",
    )

    assert media["url"] == "https://commons.example/alex.jpg"
    assert archived is False
    assert identity_updated is False
    assert notices[0][0:3] == ("Alex Silva", "player", "Arsenal")
    assert {candidate["identity_key"] for candidate in notices[0][3]} == {"wikidata:Q1", "wikidata:Q2"}
