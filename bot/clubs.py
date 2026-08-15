from .normalize import clean_text


def find_club(clubs, name):
    """Match a free-text club name against the configured clubs list
    (by canonical name or alias). Returns the club dict or None.

    Used both to verify official sources (bot/official.py) and to reject
    any extracted (player, to_club) pair — from either the regex parser or
    the Gemini fallback — that names a club we don't track. We only have
    verification sources configured for these clubs, so an unmatched club
    can never be confirmed anyway; treating it as an invalid extraction
    here also blocks the "publish unconfirmed after timeout" path from
    ever firing on a hallucinated or misspelled club name.
    """
    if not name:
        return None
    n = clean_text(name).lower()
    for club in clubs:
        aliases = [club.get("name", "")] + club.get("aliases", [])
        if any(n == clean_text(alias).lower() for alias in aliases):
            return club
    return None
