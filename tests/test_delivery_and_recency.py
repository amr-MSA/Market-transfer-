"""Tests for the reliability fixes: per-channel delivery tracking/retry,
recency-gated official/social evidence, and word-boundary name matching.
"""
import calendar
import time
from datetime import datetime, timedelta, timezone

from bot.main import _deliver, _prune_old_state
from bot.normalize import name_match
from bot.official import OfficialVerifier
from bot.publisher import TelegramPublisher


def _channels():
    return [
        {"id": "-1001", "name": "A", "enabled": True},
        {"id": "-1002", "name": "B", "enabled": True},
        {"id": "-1003", "name": "C", "enabled": True},
    ]


def test_partial_telegram_failure_is_not_marked_delivered():
    channels = _channels()
    pub = TelegramPublisher("FAKE", channels, send_delay_seconds=0)

    def flaky_send(chat_id, text):
        if chat_id == "-1002":
            raise RuntimeError("bot kicked")
        return {"ok": True}

    pub._send_to_chat = flaky_send
    delivery = {}
    complete = _deliver(pub, channels, "msg", delivery)

    assert complete is False
    assert delivery == {"-1001": "SENT", "-1002": "FAILED", "-1003": "SENT"}


def test_retry_only_targets_previously_failed_channels():
    channels = _channels()
    pub = TelegramPublisher("FAKE", channels, send_delay_seconds=0)
    delivery = {"-1001": "SENT", "-1002": "FAILED", "-1003": "SENT"}

    calls = []

    def send_ok(chat_id, text):
        calls.append(chat_id)
        return {"ok": True}

    pub._send_to_chat = send_ok
    complete = _deliver(pub, channels, "msg", delivery)

    assert calls == ["-1002"]
    assert complete is True


def test_total_telegram_outage_leaves_nothing_marked_sent():
    channels = _channels()
    pub = TelegramPublisher("FAKE", channels, send_delay_seconds=0)
    pub._send_to_chat = lambda chat_id, text: (_ for _ in ()).throw(RuntimeError("down"))

    delivery = {}
    complete = _deliver(pub, channels, "msg", delivery)

    assert complete is False
    assert all(v == "FAILED" for v in delivery.values())


def test_state_pruning_keeps_pending_and_recent_drops_old_terminal():
    now = datetime.now(timezone.utc)
    by_id = {
        "old_official": {
            "transfer_id": "old_official", "status": "OFFICIAL",
            "official_verified_at": (now - timedelta(days=90)).isoformat(),
        },
        "recent_official": {
            "transfer_id": "recent_official", "status": "OFFICIAL",
            "official_verified_at": (now - timedelta(days=5)).isoformat(),
        },
        "old_pending": {
            "transfer_id": "old_pending", "status": "WAITING_OFFICIAL",
            "discovered_at": (now - timedelta(days=200)).isoformat(),
        },
    }
    pruned = _prune_old_state(by_id, now, retention_days=60)
    assert "old_official" not in pruned
    assert "recent_official" in pruned
    assert "old_pending" in pruned  # never pruned regardless of age


def test_name_match_uses_word_boundaries():
    assert name_match("Leo", "Welcome Leo to the club!") is True
    assert name_match("Leo", "Leonardo Bonucci signs") is False
    assert name_match("Marc Cucurella", "Real Madrid sign Marc Cucurella today") is True


def test_official_evidence_requires_transfer_keyword_not_just_name():
    v = OfficialVerifier(clubs=[])
    old_style = "Former Arsenal player Bukayo Saka spoke to reporters about his career."
    announcement = "Arsenal are pleased to confirm the signing of Bukayo Saka on a permanent deal."
    assert v._is_transfer_mention("Bukayo Saka", old_style) is False
    assert v._is_transfer_mention("Bukayo Saka", announcement) is True


def test_official_recency_rejects_old_dated_entries():
    v = OfficialVerifier(clubs=[], max_age_hours=24)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    old_entry = {"published_parsed": time.gmtime(calendar.timegm((now - timedelta(days=10)).timetuple()))}
    recent_entry = {"published_parsed": time.gmtime(calendar.timegm((now - timedelta(hours=2)).timetuple()))}
    no_date_entry = {}

    assert v._entry_recent_enough(old_entry, cutoff) is False
    assert v._entry_recent_enough(recent_entry, cutoff) is True
    # No date at all: don't block, fall back to the keyword gate instead.
    assert v._entry_recent_enough(no_date_entry, cutoff) is True
