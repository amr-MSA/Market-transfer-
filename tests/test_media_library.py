from bot.media_library import MediaLibrary, TelegramMediaArchive
from bot.identity_cards import IdentityCardRegistry, TelegramIdentityCards


def _wikimedia_media():
    return {
        "url": "https://upload.wikimedia.org/example.jpg",
        "source": "wikimedia",
        "credit_name": "Photographer",
        "credit_license": "CC BY-SA 4.0",
        "credit_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
    }


def test_library_assigns_contextual_club_stint_ids_and_reuses_matching_file_id(tmp_path):
    library = MediaLibrary(tmp_path / "media_library.json")
    data = library.load()

    person, arsenal, arsenal_stint, arsenal_asset = library.reserve_contextual_ids(
        data, "Ezri Konsa", "player", "Arsenal", 2026
    )
    stored = library.add_archived_media(
        data,
        person,
        arsenal_asset,
        _wikimedia_media(),
        {"file_id": "arsenal-file", "file_unique_id": "arsenal-u", "message_id": 9, "width": 960, "height": 1200},
        arsenal,
        arsenal_stint,
    )

    same_person, villa, villa_stint, villa_asset = library.reserve_contextual_ids(
        data, "Ezri Konsa", "player", "Aston Villa", 2019
    )
    library.add_archived_media(
        data,
        same_person,
        villa_asset,
        _wikimedia_media(),
        {"file_id": "villa-file", "file_unique_id": "villa-u", "message_id": 10, "width": 960, "height": 1200},
        villa,
        villa_stint,
    )

    assert person["person_id"] == "P0000001"
    assert same_person["person_id"] == "P0000001"
    assert arsenal["club_id"] == "C0001"
    assert arsenal_stint["stint_id"] == "ST-0001-2026-0000001"
    assert arsenal_asset == "IMG-0001-2026-0000001-01"
    assert villa_asset == "IMG-0002-2019-0000001-01"
    assert stored["url"] == "arsenal-file"
    assert library.find_media(data, "Ezri Konsa", "player", club="Arsenal")["url"] == "arsenal-file"
    assert library.find_media(data, "Ezri Konsa", "player", club="Aston Villa")["url"] == "villa-file"
    assert library.find_media(data, "Ezri Konsa", "player", club="Chelsea") is None


def test_generic_portrait_is_only_a_fallback_when_no_club_image_matches(tmp_path):
    library = MediaLibrary(tmp_path / "media_library.json")
    data = library.load()
    person, asset_id = library.reserve_ids(data, "Thomas Frank", "manager")
    library.add_archived_media(
        data,
        person,
        asset_id,
        _wikimedia_media(),
        {"file_id": "generic-file", "file_unique_id": "generic-u", "message_id": 7, "width": 960, "height": 1200},
    )

    assert asset_id == "IMG-GEN-0000001-01"
    assert library.find_media(data, "Thomas Frank", "manager", club="Tottenham")["url"] == "generic-file"


def test_library_does_not_archive_media_without_a_verifiable_license():
    assert MediaLibrary.is_archivable({"url": "https://example.test/a.jpg", "source": "source"}) is False
    assert MediaLibrary.is_archivable(_wikimedia_media()) is True


def test_telegram_archive_returns_reusable_file_ids(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ok": True,
                "result": {
                    "message_id": 8,
                    "photo": [
                        {"file_id": "small", "file_unique_id": "small-u", "width": 90, "height": 90},
                        {"file_id": "large", "file_unique_id": "large-u", "width": 960, "height": 1200},
                    ],
                },
            }

    monkeypatch.setattr("bot.media_library.requests.post", lambda *args, **kwargs: Response())
    archive = TelegramMediaArchive("TOKEN", "-100777", timeout=1)

    result = archive.archive(_wikimedia_media(), {"person_id": "P0000001", "name": "Ezri Konsa"}, "IMG0000001")

    assert result == {
        "file_id": "large",
        "file_unique_id": "large-u",
        "message_id": 8,
        "width": 960,
        "height": 1200,
    }


def test_person_card_is_publishable_and_shows_optional_profile_data():
    card = {
        "person_id": "P0000001",
        "canonical_name": "Dominik Livakovic",
        "canonical_name_ar": "دومينيك ليفاكوفيتش",
        "canonical_name_original": "Dominik Livakovic",
        "entity_type": "player",
        "position_names": ["حارس مرمى"],
        "national_team_names": ["كرواتيا"],
        "nationality_names": ["كرواتيا"],
        "organization_names": ["فنربخشة"],
        "birth_date": "1995-01-09",
        "current_stats": {"season": "2025/26", "appearances": 18, "goals": 0, "source_url": "https://stats.example.test/livakovic"},
        "identity_source_url": "https://www.wikidata.org/wiki/Q18207229",
    }

    text = IdentityCardRegistry.person_text(card)

    assert "بطاقة لاعب" in text
    assert "دومينيك ليفاكوفيتش (Dominik Livakovic)" in text
    assert "المركز: حارس مرمى" in text
    assert "المنتخب: كرواتيا" in text
    assert "مشاركة: 18" in text
    assert "مصدر الإحصاءات" in text


def test_identity_card_uses_telegram_html_format(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True, "result": {"message_id": 12}}

    monkeypatch.setattr("bot.identity_cards.requests.post", lambda *args, **kwargs: (calls.append(kwargs["json"]) or Response()))
    cards = TelegramIdentityCards("TOKEN", "-100777")
    message_id = cards.upsert({"card_message_id": None}, "⚽ <b>بطاقة لاعب</b>")

    assert message_id == 12
    assert calls[0]["parse_mode"] == "HTML"
    assert calls[0]["disable_web_page_preview"] is True
