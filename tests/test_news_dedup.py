from datetime import datetime, timezone, timedelta
from bot.news_dedup import NewsDedupStore


def test_same_structured_event_is_duplicate(tmp_path):
    store = NewsDedupStore(tmp_path / "news.json", retention_days=7)
    data = {"updated_at": None, "events": []}
    event = {
        "entity_type": "player",
        "type": "انتقال",
        "player": "Player X",
        "from": "Club A",
        "to": "Club B",
    }
    store.add(data, event)
    assert store.contains(data, dict(event))


def test_different_event_type_is_not_duplicate(tmp_path):
    store = NewsDedupStore(tmp_path / "news.json", retention_days=7)
    data = {"updated_at": None, "events": []}
    transfer = {
        "entity_type": "player", "type": "انتقال",
        "player": "Player X", "from": "Club A", "to": "Club B"
    }
    injury = {
        "entity_type": "player", "type": "إصابة",
        "player": "Player X", "from": "Club B", "to": None
    }
    store.add(data, transfer)
    assert not store.contains(data, injury)


def test_manager_identity_prevents_two_appointments_from_colliding(tmp_path):
    store = NewsDedupStore(tmp_path / "news.json", retention_days=7)
    data = {"updated_at": None, "events": []}
    first = {
        "entity_type": "manager", "type": "تعيين مدرب", "from": "Club A",
        "to": None, "player": None, "person": "Manager One",
    }
    second = {**first, "person": "Manager Two"}

    store.add(data, first)

    assert store.contains(data, first)
    assert not store.contains(data, second)


def test_prune_after_seven_days(tmp_path):
    store = NewsDedupStore(tmp_path / "news.json", retention_days=7)
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    data = {"updated_at": old, "events": [{
        "entity_type": "player", "type": "انتقال",
        "player": "Old Player", "from": "A", "to": "B",
        "seen_at": old,
    }]}
    store.prune(data)
    assert data["events"] == []


def test_ttl_keeps_recent_event_across_calendar_week(tmp_path):
    store = NewsDedupStore(tmp_path / "news.json")
    sunday = datetime(2026, 8, 23, 23, 59, tzinfo=timezone.utc)
    monday = datetime(2026, 8, 24, 0, 1, tzinfo=timezone.utc)
    event = {"type": "هدف", "from": "A", "to": None, "player": "Player X"}
    data = {"week_start": None, "updated_at": None, "events": []}
    store.add(data, event, sunday)
    store.prune(data, sunday)
    assert store.contains(data, event)
    store.prune(data, monday)
    assert store.contains(data, event)
    store.prune(data, sunday + timedelta(days=7, seconds=1))
    assert not store.contains(data, event)


def test_article_is_marked_once_and_expires_after_ttl(tmp_path):
    store = NewsDedupStore(tmp_path / "news.json")
    sunday = datetime(2026, 8, 23, 23, 59, tzinfo=timezone.utc)
    monday = datetime(2026, 8, 24, 0, 1, tzinfo=timezone.utc)
    data = {"week_start": None, "updated_at": None, "events": [], "articles": []}
    store.mark_article(data, "https://example.test/article", sunday)
    store.mark_article(data, "https://example.test/article", sunday)
    assert len(data["articles"]) == 1
    assert store.has_article(data, "https://example.test/article")
    store.prune(data, monday)
    assert store.has_article(data, "https://example.test/article")
    store.prune(data, monday + timedelta(days=7, seconds=1))
    assert not store.has_article(data, "https://example.test/article")
