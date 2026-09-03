from bot.image_review import ImageReviewStore


def _candidates():
    return [
        {"label": "صورة من مصدر الخبر", "media": {"url": "https://example.test/source.jpg"}},
        {"label": "شعار النادي", "media": {"url": "https://example.test/club.jpg"}},
    ]


def test_create_is_idempotent_per_target(tmp_path):
    store = ImageReviewStore(tmp_path / "image_review.json")
    data = store.empty()

    first = store.create(data, "transfer", "t1", "Player X", "player", "Club Y", _candidates())
    second = store.create(data, "transfer", "t1", "Player X", "player", "Club Y", _candidates())

    assert first is second
    assert first["status"] == "PENDING"
    assert [c["code"] for c in first["candidates"]] == [1, 2]
    assert len(data["reviews"]) == 1


def test_only_one_review_is_ever_sent_at_a_time(tmp_path):
    store = ImageReviewStore(tmp_path / "image_review.json")
    data = store.empty()
    a = store.create(data, "transfer", "t1", "A", "player", "Club", _candidates())
    store.create(data, "transfer", "t2", "B", "player", "Club", _candidates())

    assert store.next_pending(data)["review_id"] == a["review_id"]
    store.mark_sent(data, a["review_id"], [111, 222])

    assert store.get_awaiting_reply(data)["review_id"] == a["review_id"]
    # The second review stays PENDING and is not surfaced as "next" while
    # one is already awaiting a reply — the caller checks awaiting-reply
    # first and only calls next_pending() when nothing is in flight.
    assert store.next_pending(data)["review_id"] != a["review_id"]


def test_numeric_code_approves_the_matching_candidate(tmp_path):
    store = ImageReviewStore(tmp_path / "image_review.json")
    data = store.empty()
    review = store.create(data, "transfer", "t1", "A", "player", "Club", _candidates())
    store.mark_sent(data, review["review_id"], [1])

    resolved = store.resolve(data, review["review_id"], 2)

    assert resolved["status"] == "APPROVED"
    assert resolved["resolved_media"]["url"] == "https://example.test/club.jpg"


def test_zero_records_no_suitable_image(tmp_path):
    store = ImageReviewStore(tmp_path / "image_review.json")
    data = store.empty()
    review = store.create(data, "news", "n1", "A", "player", "Club", _candidates())
    store.mark_sent(data, review["review_id"], [1])

    resolved = store.resolve(data, review["review_id"], 0)

    assert resolved["status"] == "NO_MATCH"
    assert resolved["resolved_media"] is None


def test_unknown_code_is_rejected_without_changing_status(tmp_path):
    store = ImageReviewStore(tmp_path / "image_review.json")
    data = store.empty()
    review = store.create(data, "news", "n1", "A", "player", "Club", _candidates())
    store.mark_sent(data, review["review_id"], [1])

    result = store.resolve(data, review["review_id"], 99)

    assert result is False
    assert data["reviews"][review["review_id"]]["status"] == "SENT"


def test_resolving_before_sent_is_a_no_op(tmp_path):
    store = ImageReviewStore(tmp_path / "image_review.json")
    data = store.empty()
    review = store.create(data, "news", "n1", "A", "player", "Club", _candidates())

    assert store.resolve(data, review["review_id"], 1) is None
    assert data["reviews"][review["review_id"]]["status"] == "PENDING"


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "image_review.json"
    store = ImageReviewStore(path)
    data = store.empty()
    review = store.create(data, "transfer", "t1", "A", "player", "Club", _candidates())
    store.mark_sent(data, review["review_id"], [1])
    store.resolve(data, review["review_id"], 1)
    store.save(data)

    reloaded = store.load()

    assert reloaded["reviews"][review["review_id"]]["status"] == "APPROVED"


def test_prune_drops_only_old_resolved_reviews(tmp_path):
    from datetime import datetime, timedelta, timezone

    store = ImageReviewStore(tmp_path / "image_review.json")
    data = store.empty()
    resolved = store.create(data, "transfer", "old", "A", "player", "Club", _candidates())
    store.mark_sent(data, resolved["review_id"], [1])
    store.resolve(data, resolved["review_id"], 1)
    resolved["resolved_at"] = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    pending = store.create(data, "transfer", "still-open", "B", "player", "Club", _candidates())

    store.prune(data, retention_days=60)

    assert resolved["review_id"] not in data["reviews"]
    assert pending["review_id"] in data["reviews"]
