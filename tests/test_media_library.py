from bot.media_library import MediaLibrary, TelegramMediaArchive


def _wikimedia_media():
    return {
        "url": "https://upload.wikimedia.org/example.jpg",
        "source": "wikimedia",
        "credit_name": "Photographer",
        "credit_license": "CC BY-SA 4.0",
        "credit_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
    }


def test_library_assigns_stable_person_and_asset_ids_then_reuses_file_id(tmp_path):
    library = MediaLibrary(tmp_path / "media_library.json")
    data = library.load()

    person, asset_id = library.reserve_ids(data, "Ezri Konsa", "player")
    stored = library.add_archived_media(
        data,
        person,
        asset_id,
        _wikimedia_media(),
        {"file_id": "telegram-file", "file_unique_id": "unique-file", "message_id": 9, "width": 960, "height": 1200},
    )

    assert person["person_id"] == "P0000001"
    assert asset_id == "IMG0000001"
    assert stored["url"] == "telegram-file"
    assert library.find_media(data, "Ezri Konsa", "player")["url"] == "telegram-file"


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
