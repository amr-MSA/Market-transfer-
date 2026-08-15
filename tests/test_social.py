from bot.social_x import XVerifier
from bot.social_instagram import InstagramVerifier

class Resp:
    def __init__(self, data): self._data=data
    def raise_for_status(self): pass
    def json(self): return self._data

def test_x_match(monkeypatch):
    def fake(*a, **k):
        return Resp({"data":[{"id":"123","text":"Welcome Player X to Arsenal!","created_at":"2026-08-15T10:00:00Z"}]})
    monkeypatch.setattr("bot.social_x.requests.get", fake)
    out=XVerifier("token").latest_match("42","Player X",["Arsenal"])
    assert out["kind"]=="official_x"

def test_instagram_match(monkeypatch):
    def fake(*a, **k):
        return Resp({"business_discovery":{"media":{"data":[
            {"caption":"Welcome Player X to Arsenal!","permalink":"https://instagram.com/p/abc","timestamp":"2026-08-15T10:00:00Z"}
        ]}}})
    monkeypatch.setattr("bot.social_instagram.requests.get", fake)
    out=InstagramVerifier("token","999").latest_match("arsenal","Player X",["Arsenal"])
    assert out["kind"]=="official_instagram"
