import json
from datetime import datetime, timezone

import pytest

from bot.admin import TelegramAdmin
from bot.content_types import ALL, channel_accepts, channels_for_content, normalize_content_types
from bot.news_dedup import NewsDedupStore


def test_channel_defaults_to_every_content_type_for_backward_compatibility():
    assert channel_accepts({"enabled": True}, "هدف") is True
    assert channel_accepts({"enabled": True, "content_types": ["انتقال"]}, "هدف") is False
    assert channel_accepts({"enabled": True, "content_types": ["انتقال"]}, "انتقال") is True


def test_channels_for_content_respects_enabled_state_and_subscription():
    channels = [
        {"id": "1", "enabled": True, "content_types": ["انتقال", "إعارة"]},
        {"id": "2", "enabled": True, "content_types": ["هدف"]},
        {"id": "3", "enabled": False, "content_types": [ALL]},
    ]
    assert [c["id"] for c in channels_for_content(channels, "إعارة")] == ["1"]
    assert [c["id"] for c in channels_for_content(channels, "هدف")] == ["2"]


def test_invalid_content_type_is_rejected():
    with pytest.raises(ValueError):
        normalize_content_types(["إشاعة"])


def test_calendar_week_change_keeps_recent_event(tmp_path):
    store = NewsDedupStore(tmp_path / "news.json")
    sunday = datetime(2026, 8, 23, 23, 59, tzinfo=timezone.utc)
    monday = datetime(2026, 8, 24, 0, 1, tzinfo=timezone.utc)
    event = {"type": "هدف", "from": "Club A", "to": None, "player": "Player X"}
    data = {"week_start": None, "updated_at": None, "events": []}
    store.add(data, event, sunday)
    assert store.contains(data, event)
    store.prune(data, monday)
    assert data["week_start"] is None
    assert len(data["events"]) == 1


def test_admin_can_update_channel_content_types(tmp_path):
    channels_path = tmp_path / "channels.json"
    channels_path.write_text(json.dumps({"channels": [{"id": "-1001", "name": "A", "enabled": True}]}), encoding="utf-8")
    admin = TelegramAdmin("token", ["7"], channels_path, tmp_path / "state.json", tmp_path / "updates.json")
    assert admin._set_channel_types("-1001", "انتقال,إعارة,هدف") == ["انتقال", "إعارة", "هدف"]
    saved = json.loads(channels_path.read_text(encoding="utf-8"))
    assert saved["channels"][0]["content_types"] == ["انتقال", "إعارة", "هدف"]
