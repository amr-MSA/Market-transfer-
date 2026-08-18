from datetime import datetime, timezone

from bot.social_x import XVerifier
from bot.social_instagram import InstagramVerifier

class Resp:
    def __init__(self, data): self._data=data
    def raise_for_status(self): pass
    def json(self): return self._data

def test_x_match(monkeypatch):
    def fake(*a, **k):
        return Resp({"data":[{"id":"123","text":"Welcome Player X to Arsenal!","created_at":datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}]})
    monkeypatch.setattr("bot.social_x.requests.get", fake)
    out=XVerifier("token").latest_match("42","Player X",["Arsenal"])
    assert out["kind"]=="official_x"

def test_instagram_match(monkeypatch):
    def fake(*a, **k):
        return Resp({"business_discovery":{"media":{"data":[
            {"caption":"Welcome Player X to Arsenal!","permalink":"https://instagram.com/p/abc","timestamp":datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        ]}}})
    monkeypatch.setattr("bot.social_instagram.requests.get", fake)
    out=InstagramVerifier("token","999").latest_match("arsenal","Player X",["Arsenal"])
    assert out["kind"]=="official_instagram"

def test_x_rejects_unrelated_player_mention(monkeypatch):
    def fake(*a, **k):
        return Resp({"data":[{"id":"123","text":"Great performance from Player X for Arsenal!","created_at":datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}]})
    monkeypatch.setattr("bot.social_x.requests.get", fake)
    assert XVerifier("token").latest_match("42", "Player X", ["Arsenal"]) is None
