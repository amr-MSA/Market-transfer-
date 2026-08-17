from bot.event_deduplicator import EventDeduplicator


def test_normalization():
    a = EventDeduplicator.normalize(
        "BREAKING: Arsenal agree deal for Player X!"
    )
    b = EventDeduplicator.normalize(
        "Arsenal agree deal for Player X"
    )
    assert EventDeduplicator.similarity(a, b) > 0.8


def test_different_events_can_be_distinguished():
    a = "Player X joins Arsenal"
    b = "Player Y joins Chelsea"
    assert EventDeduplicator.similarity(a, b) < 0.8


def test_new_event_is_created():
    events = []
    d = EventDeduplicator(events)
    event, method = d.find_or_create(
        {
            "title": "Arsenal sign Player X",
            "category": "TRANSFER_NEWS",
            "published_at": "2026-08-15T12:00:00+00:00",
        },
        events,
    )
    assert method == "new"
    assert event["event_id"]
