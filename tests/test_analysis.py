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
    message = official_message(
        "A < B", "Club A", "Club B", "https://example.test?a=1&b=2", analysis,
        editorial={"headline": "أ < ب", "lead": "أعلن النادي الصفقة رسميًا."},
    )
    assert "أ &lt; ب" in message
    assert "تحليل سريع" not in message
    assert "a=1&amp;b=2" in message


def test_transfer_message_never_falls_back_to_latin_names_without_editorial():
    message = official_message("Ayyoub Bouaddi", "Lille", "Barcelona", "https://example.test")
    assert "Ayyoub" not in message
    assert "Lille" not in message
    assert "Barcelona" not in message


def test_editorial_transfer_message_is_short_and_uses_arabic_names():
    editorial = {
        "section": "انتقال",
        "headline": "أرسنال يتوصل إلى اتفاق لضم إزري كونسا",
        "lead": "أعلن أرسنال التعاقد مع إزري كونسا قادمًا من أستون فيلا ضمن تدعيماته للموسم الجديد.",
        "detail": "التفاصيل الرسمية قيد الانتظار.",
        "player_ar": "إزري كونسا",
        "player_original": "Ezri Konsa",
        "from_ar": "أستون فيلا",
        "from_original": "Aston Villa",
        "to_ar": "أرسنال",
        "to_original": "Arsenal",
        "comment_ar": "إضافة تمنح أرسنال خيارًا جديدًا في الخط الخلفي.",
        }

    message = official_message(
        "Ezri Konsa", "Aston Villa", "Arsenal", "https://example.test", editorial=editorial
    )
    assert "إزري كونسا" in message
    assert "Ezri Konsa" not in message
    assert "أعلن أرسنال التعاقد" in message
    assert "تحليل سريع" not in message
    assert message.count("إزري كونسا") >= 1
    assert "❝إضافة تمنح أرسنال خيارًا جديدًا في الخط الخلفي.❞" in message
    assert "التفاصيل الرسمية قيد الانتظار" not in message


def test_news_message_contains_structured_summary():
    analysis = analyze_news_event(
        {"entity_type": "player", "type": "إصابة", "player": "Player X", "from": "Club A"},
        {"title": "Player X injured", "source": "Source"},
    )
    message = football_news_message({"title": "Player X injured", "source": "Source", "url": "https://example.test"}, analysis)
    assert "🩺 <b>إصابة</b>" in message
    assert "Player X" in message
