import json

import pytest

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
