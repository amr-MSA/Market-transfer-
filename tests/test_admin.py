import json

import pytest

import bot.admin as admin_module
from bot.admin import TelegramAdmin


class Publisher:
    channels = []

    def send(self, text, channels=None):
        return []


def make_admin(tmp_path):
    channels = tmp_path / "channels.json"
    channels.write_text(json.dumps({"channels": []}), encoding="utf-8")
    updates = tmp_path / "updates.json"
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"media_library_enabled": True}), encoding="utf-8")
    return TelegramAdmin(
        "token", ["7"], channels, tmp_path / "state.json", updates,
        timeout=1, settings_path=settings,
    )


def test_channel_id_validation():
    assert TelegramAdmin._normalize_channel_id("-1001234567890") == "-1001234567890"
    assert TelegramAdmin._normalize_channel_id("@my_channel") == "@my_channel"
    assert TelegramAdmin._normalize_channel_id("https://t.me/my_channel") is None
    assert TelegramAdmin._normalize_channel_id("not-a-channel") is None


def test_add_list_toggle_and_remove_channel(tmp_path):
    admin = make_admin(tmp_path)
    assert admin._add_channel({"id": "-1001234567890", "name": "Main"}) is True
    assert admin._add_channel({"id": "-1001234567890", "name": "Renamed"}) is False
    assert "Renamed" in admin._list_channels()
    assert admin._set_channel_enabled("-1001234567890", False) is True
    assert "disabled" in admin._list_channels()
    assert admin._remove_channel("-1001234567890") is True
    assert "No channels configured" in admin._list_channels()


def test_invalid_channel_is_rejected(tmp_path):
    admin = make_admin(tmp_path)
    with pytest.raises(ValueError):
        admin._add_channel({"id": "https://t.me/example", "name": "Example"})


def test_addchannel_command_works_without_forwarded_message(tmp_path):
    admin = make_admin(tmp_path)
    sent = []
    admin._send = lambda chat_id, text: sent.append((chat_id, text))
    admin._api = lambda method, payload=None: [{
        "update_id": 1,
        "message": {
            "from": {"id": 7},
            "chat": {"id": 7},
            "text": "/addchannel -1001234567890 Main Channel",
        },
    }] if method == "getUpdates" else None

    summary = admin.process(Publisher())
    saved = json.loads((tmp_path / "channels.json").read_text(encoding="utf-8"))
    assert summary == "processed 1 update(s)"
    assert saved["channels"] == [{
        "id": "-1001234567890",
        "name": "Main Channel",
        "enabled": True,
        "content_types": ["*"],
    }]
    assert "تمت الإضافة" in sent[0][1]


def test_medialibrary_command_links_a_forwarded_private_channel(tmp_path):
    admin = make_admin(tmp_path)
    sent = []
    admin._send = lambda chat_id, text: sent.append((chat_id, text))
    admin._api = lambda method, payload=None: [
        {
            "update_id": 1,
            "message": {"from": {"id": 7}, "chat": {"id": 7}, "text": "/setmedialibrary"},
        },
        {
            "update_id": 2,
            "message": {
                "from": {"id": 7},
                "chat": {"id": 7},
                "forward_origin": {"type": "channel", "chat": {"id": -100777, "title": "Media Vault"}},
            },
        },
    ] if method == "getUpdates" else None

    admin.process(Publisher())

    settings = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert settings["media_library_channel_id"] == "-100777"
    assert settings["media_library_channel_name"] == "Media Vault"
    assert settings["media_library_auto_archive"] is True
    assert any("تم ربط مكتبة الصور" in text for _, text in sent)


def test_addchannel_resolves_a_public_telegram_link_and_checks_posting_rights(tmp_path):
    admin = make_admin(tmp_path)
    sent = []
    admin._send = lambda chat_id, text: sent.append((chat_id, text))

    def api(method, payload=None):
        if method == "getUpdates":
            return [{"update_id": 1, "message": {"from": {"id": 7}, "chat": {"id": 7}, "text": "/addchannel https://t.me/arsenal"}}]
        if method == "getChat":
            assert payload == {"chat_id": "@arsenal"}
            return {"id": -100999, "type": "channel", "title": "Arsenal"}
        if method == "getMe":
            return {"id": 77}
        if method == "getChatMember":
            assert payload == {"chat_id": -100999, "user_id": 77}
            return {"status": "administrator", "can_post_messages": True}
        return None

    admin._api = api
    admin.process(Publisher())

    saved = json.loads((tmp_path / "channels.json").read_text(encoding="utf-8"))
    assert saved["channels"][0]["id"] == "-100999"
    assert saved["channels"][0]["name"] == "Arsenal"
    assert any("تمت الإضافة" in text for _, text in sent)


def test_identity_cards_channel_links_from_forwarded_message(tmp_path):
    admin = make_admin(tmp_path)
    sent = []
    admin._send = lambda chat_id, text: sent.append((chat_id, text))
    admin._api = lambda method, payload=None: [
        {"update_id": 1, "message": {"from": {"id": 7}, "chat": {"id": 7}, "text": "/setidentitylibrary"}},
        {
            "update_id": 2,
            "message": {
                "from": {"id": 7},
                "chat": {"id": 7},
                "forward_origin": {"type": "channel", "chat": {"id": -100555, "title": "Identity Cards"}},
            },
        },
    ] if method == "getUpdates" else None

    admin.process(Publisher())

    settings = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert settings["identity_cards_channel_id"] == "-100555"
    assert settings["identity_cards_channel_name"] == "Identity Cards"
    assert any("تم ربط قناة بطاقات الهوية" in text for _, text in sent)


def test_addmedia_archives_a_contextual_club_image(tmp_path, monkeypatch):
    admin = make_admin(tmp_path)
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"media_library_enabled": True, "media_library_channel_id": "-100777"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(admin_module, "ROOT", tmp_path)
    class IdentitySource:
        def __init__(self, *args, **kwargs):
            pass

        def candidates(self, name, entity_type, organization=None):
            return [{
                "identity_key": "wikidata:Q99",
                "canonical_name": name,
                "aliases": [name],
                "birth_date": "1997-10-23",
                "nationality_ids": ["Q145"],
                "position_ids": ["Q193592"],
                "source_url": "https://www.wikidata.org/wiki/Q99",
                "verified_at": "2026-08-25T00:00:00+00:00",
            }]

    monkeypatch.setattr(admin_module, "WikidataIdentitySource", IdentitySource)
    monkeypatch.setattr(
        admin_module.TelegramMediaArchive,
        "archive_manual",
        lambda self, *args: {
            "file_id": "library-file",
            "file_unique_id": "library-unique",
            "message_id": 18,
            "width": 960,
            "height": 1200,
        },
    )
    sent = []
    admin._send = lambda chat_id, text: sent.append((chat_id, text))
    admin._api = lambda method, payload=None: [
        {
            "update_id": 1,
            "message": {
                "from": {"id": 7},
                "chat": {"id": 7},
                "text": '/addmedia "Ezri Konsa" player Arsenal 2026 https://commons.example/konsa "CC BY-SA 4.0"',
            },
        },
        {
            "update_id": 2,
            "message": {
                "from": {"id": 7},
                "chat": {"id": 7},
                "photo": [{"file_id": "incoming-small"}, {"file_id": "incoming-large"}],
            },
        },
    ] if method == "getUpdates" else None

    admin.process(Publisher())

    data = json.loads((tmp_path / "data" / "media_library.json").read_text(encoding="utf-8"))
    asset = data["assets"]["IMG-0001-2026-0000001-01"]
    assert asset["club_id"] == "C0001"
    assert asset["stint_id"] == "ST-0001-2026-0000001"
    assert asset["telegram_file_id"] == "library-file"
    cards = json.loads((tmp_path / "data" / "identity_cards.json").read_text(encoding="utf-8"))
    assert cards["people"]["P0000001"]["canonical_name"] == "Ezri Konsa"
    assert cards["people"]["P0000001"]["identity_key"] == "wikidata:Q99"
    assert cards["people"]["P0000001"]["identity_status"] == "VERIFIED"
    assert cards["organizations"]["C0001"]["canonical_name"] == "Arsenal"
    assert any("أُضيفت الصورة" in text for _, text in sent)


def test_unknown_command_returns_structured_arabic_help(tmp_path):
    admin = make_admin(tmp_path)
    sent = []
    admin._send = lambda chat_id, text: sent.append((chat_id, text))
    admin._api = lambda method, payload=None: [
        {"update_id": 1, "message": {"from": {"id": 7}, "chat": {"id": 7}, "text": "/help"}},
    ] if method == "getUpdates" else None

    admin.process(Publisher())

    assert "📡 القنوات والنشر" in sent[0][1]
    assert "🖼 مكتبة الصور والهوية" in sent[0][1]
    assert "/addmedia" in sent[0][1]


def test_addmedia_reports_all_ambiguous_identity_candidates(tmp_path, monkeypatch):
    admin = make_admin(tmp_path)
    (tmp_path / "settings.json").write_text(
        json.dumps({"media_library_enabled": True, "media_library_channel_id": "-100777"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(admin_module, "ROOT", tmp_path)

    class IdentitySource:
        def __init__(self, *args, **kwargs):
            pass

        def candidates(self, name, entity_type, organization=None):
            return [
                {"identity_key": "wikidata:Q1", "canonical_name": name, "aliases": ["Alias 1"], "birth_date": "1990-01-01", "nationality_ids": ["Q1"], "position_ids": ["Q2"], "organization_ids": ["Q3"], "source_url": "https://www.wikidata.org/wiki/Q1"},
                {"identity_key": "wikidata:Q2", "canonical_name": name, "aliases": ["Alias 2"], "birth_date": "1995-01-01", "nationality_ids": ["Q4"], "position_ids": ["Q5"], "organization_ids": ["Q6"], "source_url": "https://www.wikidata.org/wiki/Q2"},
            ]

    monkeypatch.setattr(admin_module, "WikidataIdentitySource", IdentitySource)
    sent = []
    admin._send = lambda chat_id, text: sent.append((chat_id, text))
    admin._api = lambda method, payload=None: [
        {"update_id": 1, "message": {"from": {"id": 7}, "chat": {"id": 7}, "text": '/addmedia "Alex Silva" player Arsenal 2026 https://commons.example/alex "CC BY-SA 4.0"'}},
        {"update_id": 2, "message": {"from": {"id": 7}, "chat": {"id": 7}, "photo": [{"file_id": "incoming"}]}},
    ] if method == "getUpdates" else None

    admin.process(Publisher())

    report = sent[-1][1]
    assert "هوية ملتبسة" in report
    assert "wikidata:Q1" in report
    assert "wikidata:Q2" in report
    assert not (tmp_path / "data" / "media_library.json").exists()


def test_ambiguity_report_is_sent_to_every_admin(tmp_path):
    admin = make_admin(tmp_path)
    admin.admin_ids = {"7", "8"}
    sent = []
    admin._send = lambda chat_id, text: sent.append((chat_id, text))

    admin.report_identity_ambiguity("Alex Silva", "player", "Arsenal", [{"identity_key": "wikidata:Q1", "canonical_name": "Alex Silva"}])

    assert {str(chat_id) for chat_id, _ in sent} == {"7", "8"}
    assert all("wikidata:Q1" in text for _, text in sent)
