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
