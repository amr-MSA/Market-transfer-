import json

from bot.gemini_rate_limit import GeminiRateLimiter
from bot.news_extractor import GeminiNewsExtractor


class _OkResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "candidates": [{
                "content": {
                    "parts": [{"text": json.dumps({
                        "type": "أخبار ناد",
                        "from": "Arsenal",
                        "to": None,
                        "player": None,
                        "person": None,
                        "entity_type": "club",
                    })}]
                }
            }]
        }


class _BusyResponse:
    status_code = 429
    headers = {"Retry-After": "3"}

    def raise_for_status(self):
        return None


def test_rate_limiter_spaces_consecutive_requests():
    now = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    limiter = GeminiRateLimiter(min_interval_seconds=4, max_retries=0, sleep_fn=sleep, clock=lambda: now[0])
    limiter.post(lambda: _OkResponse())
    now[0] = 1.0
    limiter.post(lambda: _OkResponse())

    assert sleeps == [3.0]


def test_rate_limiter_retries_a_429_with_retry_after():
    sleeps = []
    responses = iter([_BusyResponse(), _OkResponse()])
    limiter = GeminiRateLimiter(min_interval_seconds=0, max_retries=1, retry_backoff_seconds=1, sleep_fn=sleeps.append)

    response = limiter.post(lambda: next(responses))

    assert response.status_code == 200
    assert sleeps == [3.0]


def test_news_extractor_marks_rate_limit_failure_as_transient(monkeypatch):
    limiter = GeminiRateLimiter(min_interval_seconds=0, max_retries=0, sleep_fn=lambda _: None)
    monkeypatch.setattr("bot.news_extractor.requests.post", lambda *args, **kwargs: _BusyResponse())
    extractor = GeminiNewsExtractor("KEY", rate_limiter=limiter)

    event = extractor.extract({"title": "Arsenal update", "summary": "Arsenal update", "source": "BBC", "url": "https://example.test"})

    assert event is None
    assert extractor.last_failure_transient is True
