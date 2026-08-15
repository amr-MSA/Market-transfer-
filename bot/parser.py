import re
from .normalize import clean_text

# Word building blocks for proper-noun capture. Case sensitivity is
# deliberate here (NOT wrapped in re.I) — this is what actually
# distinguishes "Marc Cucurella" (a name) from "reach" or "agreement"
# (ordinary lowercase words in the sentence). Only the connector keywords
# ("to", "here we go", "reach", ...) use inline (?i:...) case-insensitivity,
# scoped to just that piece of the pattern.
_PLAYER = r"[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'-]*(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'-]*){1,3}"
_CLUB = r"[A-Z][A-Za-zÀ-ÖØ-öø-ÿ0-9.'&-]*(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ0-9.'&-]*){0,3}"
_HWG = r"(?i:here\s+we\s+go)"

# Ordinary sentence words that must never be accepted as part of a
# player/club name. Guards against a regex accidentally swallowing
# non-name words when the surrounding sentence structure is unusual.
_STOPWORDS = {
    "deal", "here", "we", "go", "official", "confirmed", "medical", "fee",
    "loan", "buy", "option", "clause", "terms", "verbal", "agreement",
    "agreements", "and", "from", "with", "for", "reach", "reached",
    "reaches", "sign", "signs", "signing", "signed", "joins", "join",
    "today", "now", "new", "talks", "club", "clubs", "exclusive", "breaking",
}

_PATTERNS = [
    # "Player to Club, here we go"
    re.compile(
        rf"(?P<player>{_PLAYER})\s+(?i:to)\s+(?P<club>{_CLUB}),?\s+"
        rf"(?i:confirmed\s+and\s+)?{_HWG}"
    ),
    # "Club reach(es)/agree(s) (a) (verbal) deal/agreement to sign Player ... here we go"
    re.compile(
        rf"(?P<club>{_CLUB})\s+(?i:reach(?:es|ed)?|agrees?)\s+"
        rf"(?i:an?\s+)?(?i:verbal\s+)?(?i:deal|agreement)\s+(?i:to\s+sign)\s+"
        rf"(?P<player>{_PLAYER})(?:\s+(?i:from)\s+(?P<from_club>{_CLUB}))?.*?{_HWG}",
        re.S,
    ),
    # "Player joins Club ... here we go"
    re.compile(
        rf"(?P<player>{_PLAYER})\s+(?i:joins)\s+(?P<club>{_CLUB})"
        rf"(?:\s+(?i:from)\s+(?P<from_club>{_CLUB}))?.*?{_HWG}",
        re.S,
    ),
    # "Club sign(s) Player ... here we go"
    re.compile(
        rf"(?P<club>{_CLUB})\s+(?i:sign|signs)\s+(?P<player>{_PLAYER})"
        rf"(?:\s+(?i:from)\s+(?P<from_club>{_CLUB}))?.*?{_HWG}",
        re.S,
    ),
]


def _valid_name(name):
    if not name:
        return False
    words = name.split()
    if not words:
        return False
    if any(w.lower() in _STOPWORDS for w in words):
        return False
    return True


def parse_transfer(text):
    t = clean_text(text)
    for pattern in _PATTERNS:
        m = pattern.search(t)
        if not m:
            continue
        d = m.groupdict()
        player = clean_text(d.get("player"))
        club = clean_text(d.get("club"))
        from_club = clean_text(d.get("from_club")) if d.get("from_club") else None

        if not _valid_name(player) or not _valid_name(club):
            continue
        if len(player.split()) < 2:
            continue
        if from_club is not None and not _valid_name(from_club):
            from_club = None
        if from_club and from_club.lower() == club.lower():
            from_club = None

        return {"player": player, "to_club": club, "from_club": from_club}
    return {"player": None, "to_club": None, "from_club": None}
