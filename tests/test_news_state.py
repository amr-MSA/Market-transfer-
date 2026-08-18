from bot.news_state import NewsState


def test_failed_news_delivery_is_not_published(tmp_path):
    state = NewsState(tmp_path / "news.json")
    data = state.load()
    state.mark_result(data, "a", [{"id": "1", "ok": False}], None)
    assert data["published"]["a"]["published_at"] is None
    assert data["published"]["a"]["delivery"]["1"] == "FAILED"


def test_successful_news_delivery_is_published(tmp_path):
    state = NewsState(tmp_path / "news.json")
    data = state.load()
    state.mark_result(data, "a", [{"id": "1", "ok": True}], None)
    assert data["published"]["a"]["published_at"]
