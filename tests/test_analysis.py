from bot.analysis import analyze_news_event, analyze_transfer
from bot.formatting import football_news_message, official_message


def test_transfer_analysis_distinguishes_official_and_unconfirmed():
    transfer = {"player": "Player X", "from_club": "Club A", "to_club": "Club B"}
    official = analyze_transfer(transfer, "OFFICIAL")
    waiting = analyze_transfer(transfer, "HERE_WE_GO")
    assert official["status_score"] == 100
    assert waiting["status_score"] == 75
    assert "غير رسمي" in waiting["stage"]
    assert "تأكيد رسمي" in waiting["recommendation"]


def test_news_analysis_reports_completeness_and_importance():
    analysis = analyze_news_event(
        {
            "entity_type": "player",
            "type": "انتقال",
            "player": "Player X",
            "from": "Club A",
            "to": "Club B",
        },
        {"title": "Player X joins Club B", "source": "Source"},
    )
    assert analysis["importance"] == "عالية"
    assert analysis["completeness_score"] == 100
    assert "Player X" in analysis["summary"]


def test_messages_include_analysis_and_escape_html():
    analysis = analyze_transfer(
        {"player": "A < B", "from_club": "Club A", "to_club": "Club B"},
        "OFFICIAL",
    )
    message = official_message("A < B", "Club A", "Club B", "https://example.test?a=1&b=2", analysis)
    assert "A &lt; B" in message
    assert "تحليل سريع" in message
    assert "a=1&amp;b=2" in message


def test_news_message_contains_structured_summary():
    analysis = analyze_news_event(
        {"entity_type": "player", "type": "إصابة", "player": "Player X", "from": "Club A"},
        {"title": "Player X injured", "source": "Source"},
    )
    message = football_news_message({"title": "Player X injured", "source": "Source", "url": "https://example.test"}, analysis)
    assert "التصنيف: إصابة" in message
    assert "Player X" in message
