import json, os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
from .clubs import find_club
from .fabrizio import FabrizioSource
from .formatting import official_message, here_we_go_message
from .gemini_extractor import GeminiExtractor
from .normalize import contains_here_we_go, fingerprint
from .official import OfficialVerifier
from .parser import parse_transfer
from .social_x import XVerifier
from .social_instagram import InstagramVerifier
from .publisher import TelegramPublisher
from .state import StateStore

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

_TERMINAL_STATES = {"OFFICIAL", "HERE_WE_GO"}


def load_json(path):
    with path.open(encoding="utf-8") as f: return json.load(f)


def _deliver(publisher, channels, text, delivery_state):
    """Send `text` only to channels not already marked SENT in
    delivery_state, and merge the results back in. Returns True once every
    currently-enabled channel is marked SENT (i.e. delivery is complete).

    This is what prevents a transfer from being marked OFFICIAL/HERE_WE_GO
    when Telegram delivery actually failed: a partial or total failure
    leaves the transfer's status untouched, so the next run retries only
    the channels that are still missing.
    """
    pending = [c for c in channels if delivery_state.get(c["id"]) != "SENT"]
    if pending:
        results = publisher.send(text, channels=pending)
        for r in results:
            delivery_state[r["id"]] = "SENT" if r["ok"] else "FAILED"
            if not r["ok"]:
                print(f"[publish-failed] channel={r['channel']} id={r['id']} error={r['error']}")
    return all(delivery_state.get(c["id"]) == "SENT" for c in channels)


def _prune_old_state(by_id, now, retention_days):
    """Drop terminal (OFFICIAL/HERE_WE_GO) records older than the retention
    window so data/transfers.json doesn't grow forever. Anything still
    WAITING_OFFICIAL (or with pending deliveries) is always kept regardless
    of age — it isn't done yet.
    """
    cutoff = now - timedelta(days=retention_days)
    kept = {}
    for tid, t in by_id.items():
        if t["status"] not in _TERMINAL_STATES:
            kept[tid] = t
            continue
        marker = t.get("official_verified_at") or t.get("unconfirmed_published_at") or t.get("discovered_at")
        try:
            when = datetime.fromisoformat(marker.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            when = now  # malformed/missing timestamp: keep it, don't guess
        if when >= cutoff:
            kept[tid] = t
    return kept


def main():
    settings = load_json(ROOT/"config/settings.json")
    clubs = load_json(ROOT/"config/clubs.json")["clubs"]
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token: raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    channels_config = load_json(ROOT/"config/channels.json")["channels"]
    channels = [c for c in channels_config if c.get("enabled", True)]
    if not channels:
        raise RuntimeError("No enabled channels in config/channels.json")

    store = StateStore(ROOT/"data/transfers.json")
    state = store.load()
    by_id = {x["transfer_id"]:x for x in state}

    source = FabrizioSource(settings["fabrizio_channel"], settings["request_timeout_seconds"], settings["user_agent"])
    x_verifier = None
    instagram_verifier = None
    social_max_age = settings.get("social_check_max_age_hours", 24)
    if settings.get("social_verification_enabled", True):
        if settings.get("x_enabled", True) and os.getenv("X_API_BEARER_TOKEN"):
            x_verifier = XVerifier(os.getenv("X_API_BEARER_TOKEN"), settings["request_timeout_seconds"], social_max_age)
        if settings.get("instagram_enabled", True) and os.getenv("INSTAGRAM_ACCESS_TOKEN") and os.getenv("INSTAGRAM_APP_IG_USER_ID"):
            instagram_verifier = InstagramVerifier(
                os.getenv("INSTAGRAM_ACCESS_TOKEN"),
                os.getenv("INSTAGRAM_APP_IG_USER_ID"),
                settings["request_timeout_seconds"],
                social_max_age
            )

    gemini_extractor = None
    if settings.get("gemini_enabled", True) and os.getenv("GEMINI_API_KEY"):
        gemini_extractor = GeminiExtractor(
            os.getenv("GEMINI_API_KEY"),
            settings["request_timeout_seconds"],
            settings.get("gemini_model", "gemini-3.6-flash")
        )

    verifier = OfficialVerifier(
        clubs,
        settings["request_timeout_seconds"],
        settings["user_agent"],
        settings["google_news_enabled"],
        x_verifier=x_verifier,
        instagram_verifier=instagram_verifier,
        max_age_hours=settings.get("official_check_max_age_hours", 24)
    )
    publisher = TelegramPublisher(
        token,
        channels,
        settings["request_timeout_seconds"],
        settings.get("channel_send_delay_seconds", 0.35)
    )

    for post in source.fetch():
        text = post["text"]
        p = parse_transfer(text)
        extraction_method = "regex"

        # Regex is the primary (free, instant) path. Gemini is only called
        # as a fallback when the regex could not confidently parse a post
        # that does contain "here we go" — this keeps usage well within
        # the free tier instead of calling the API on every single post.
        if (not p["player"] or not p["to_club"]) and gemini_extractor and contains_here_we_go(text):
            p = gemini_extractor.extract(text)
            extraction_method = "gemini"

        # Reject single-word "names" regardless of extraction method — a
        # bare first name/nickname is a common source of false matches
        # later in social/official verification.
        if p.get("player") and len(p["player"].split()) < 2:
            p["player"] = None

        # A club we don't track can never be verified anyway (see
        # OfficialVerifier/find_club), and treating an unmatched name as
        # invalid here also blocks a hallucinated/misspelled club from
        # ever reaching the "publish unconfirmed after timeout" path.
        matched_club = find_club(clubs, p.get("to_club")) if p.get("to_club") else None
        if not p["player"] or not p["to_club"] or not matched_club:
            # Never invent or publish an identity from an ambiguous post.
            continue
        p["to_club"] = matched_club["name"]

        tid = fingerprint(p["player"], p["from_club"] or "", p["to_club"])
        if tid not in by_id:
            by_id[tid] = {
                "transfer_id":tid, **p,
                "extraction_method":extraction_method,
                "fabrizio_url":post["url"],
                "fabrizio_text":post["text"],
                "discovered_at":post["discovered_at"],
                "status":"WAITING_OFFICIAL",
                "official_sent":False,
                "official_delivery":{},
                "unconfirmed_sent":False,
                "unconfirmed_delivery":{}
            }

    now = datetime.now(timezone.utc)
    expiry = timedelta(hours=settings["official_max_age_hours"])

    for t in by_id.values():
        if t["status"] not in {"WAITING_OFFICIAL"}: continue
        t.setdefault("official_delivery", {})
        t.setdefault("unconfirmed_delivery", {})

        # Cache evidence once found so a channel outage doesn't force us to
        # re-run web/API verification every cycle — we only need to keep
        # retrying delivery, not re-verify something already confirmed.
        evidence = t.get("official_evidence")
        if not evidence:
            found = verifier.verify(t["player"], t["to_club"])
            if found and found.get("kind") in {"official_x", "official_instagram", "official_feed", "official_site", "official_domain_discovery"}:
                evidence = found
                t["official_evidence"] = evidence

        if evidence:
            text = official_message(t["player"], t.get("from_club"), t["to_club"], evidence["url"])
            delivered = _deliver(publisher, channels, text, t["official_delivery"])
            if delivered:
                t.update(
                    status="OFFICIAL",
                    official_sent=True,
                    official_url=evidence["url"],
                    official_source=evidence["source"],
                    official_evidence_kind=evidence["kind"],
                    official_verified_at=now.isoformat()
                )
            # else: stays WAITING_OFFICIAL with evidence cached; retried next cycle
            continue

        discovered = datetime.fromisoformat(t["discovered_at"].replace("Z","+00:00"))
        if now - discovered >= expiry and settings["publish_unconfirmed"]:
            text = here_we_go_message(t["player"], t.get("from_club"), t["to_club"], t["fabrizio_url"])
            delivered = _deliver(publisher, channels, text, t["unconfirmed_delivery"])
            if delivered:
                t.update(status="HERE_WE_GO", unconfirmed_sent=True, unconfirmed_published_at=now.isoformat())
            # else: retried next cycle

    by_id = _prune_old_state(by_id, now, settings.get("state_retention_days", 60))
    store.save(list(by_id.values()))

if __name__ == "__main__":
    main()
