import json

from bot.editorial import GeminiEditorialWriter


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _payload(obj):
    return {
        "candidates": [{
            "content": {
                "parts": [{"text": json.dumps(obj, ensure_ascii=False)}]
            }
        }]
    }


def test_editorial_writer_returns_arabic_fields_and_section(monkeypatch, tmp_path):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(json)
        return _Response(_payload({
            "headline": "أرسنال يتوصل إلى اتفاق لضم إزري كونسا",
            "lead": "المدافع إزري كونسا (Ezri Konsa) ينتقل من أستون فيلا (Aston Villa) إلى أرسنال (Arsenal).",
            "detail": "الخبر بصيغة صحفية مختصرة، بانتظار التفاصيل الرسمية.",
            "player_ar": "إزري كونسا",
            "player_original": "Ezri Konsa",
            "from_ar": "أستون فيلا",
            "from_original": "Aston Villa",
            "to_ar": "أرسنال",
            "to_original": "Arsenal",
        }))

    monkeypatch.setattr("bot.editorial.requests.post", fake_post)
    writer = GeminiEditorialWriter("KEY", tmp_path, model="gemini-3.6-flash")
    result = writer.write(
        {"title": "Arsenal agree deal", "summary": "Konsa move", "source": "BBC"},
        {"type": "انتقال", "from": "Aston Villa", "to": "Arsenal", "player": "Ezri Konsa"},
        status="خبر صحفي",
    )

    assert result["section"] == "انتقال"
    assert result["headline"].startswith("أرسنال")
    assert result["player_ar"] == "إزري كونسا"
    request_text = calls[0]["contents"][0]["parts"][0]["text"]
    request_payload = json.loads(request_text)
    assert "global_editorial_rules" in request_payload
    assert "section_rules" in request_payload


def test_editorial_writer_rejects_overlong_output(monkeypatch, tmp_path):
    def fake_post(url, headers, json, timeout):
        return _Response(_payload({
            "headline": "x" * 181,
            "lead": "مختصر",
        }))

    monkeypatch.setattr("bot.editorial.requests.post", fake_post)
    writer = GeminiEditorialWriter("KEY", tmp_path)
    result = writer.write({"title": "x"}, {"type": "أخرى", "from": "جهة"})
    assert result is None


def test_editorial_writer_uses_other_for_unknown_section(monkeypatch, tmp_path):
    def fake_post(url, headers, json, timeout):
        return _Response(_payload({"headline": "خبر كروي جديد", "lead": "تفاصيل من المصدر."}))

    monkeypatch.setattr("bot.editorial.requests.post", fake_post)
    writer = GeminiEditorialWriter("KEY", tmp_path)
    result = writer.write({"title": "x"}, {"type": "قسم غير موجود", "from": "جهة"})
    assert result["section"] == "أخرى"
