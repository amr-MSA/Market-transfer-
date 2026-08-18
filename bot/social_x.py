import requests
from datetime import datetime, timedelta, timezone
from .normalize import clean_text, name_match
import re

_TRANSFER_KEYWORDS = re.compile(
    r"\b(sign(?:s|ed|ing)?|join(?:s|ed|ing)?|official|confirm(?:s|ed)?|"
    r"complet(?:e|es|ed|ion)|welcome|unveil(?:s|ed)?|deal|transfer|"
    r"loan|permanent|medical|contract)\b",
    re.I,
)

class XVerifier:
    """Reads recent posts from a configured official X account.

    Requires X_API_BEARER_TOKEN. The account's numeric user ID should be
    configured; resolving usernames dynamically is deliberately avoided.
    """

    def __init__(self, bearer_token, timeout=20, max_age_hours=24):
        self.token = bearer_token
        self.timeout = timeout
        self.max_age_hours = max_age_hours

    def latest_match(self, user_id, player, club_aliases):
        if not self.token or not user_id:
            return None

        since_dt = datetime.now(timezone.utc) - timedelta(hours=self.max_age_hours)
        url = f"https://api.x.com/2/users/{user_id}/tweets"
        params = {
            "max_results": 20,
            "tweet.fields": "created_at,public_metrics",
            "exclude": "retweets,replies",
            # Ask the API to only return posts within the window, and also
            # re-check created_at ourselves below — belt and suspenders,
            # since a stale post about this player from months ago must
            # never be treated as confirming today's transfer.
            "start_time": since_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        r = requests.get(
            url, params=params,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=self.timeout
        )
        r.raise_for_status()
        data = r.json().get("data", [])

        for post in data:
            created_at = post.get("created_at")
            if created_at and not self._within_window(created_at, since_dt):
                continue
            text = clean_text(post.get("text", ""))
            if not name_match(player, text):
                continue
            if not any(name_match(alias, text) for alias in club_aliases if alias):
                continue
            if not _TRANSFER_KEYWORDS.search(text):
                continue
            return {
                "url": f"https://x.com/i/web/status/{post['id']}",
                "source": "official_x",
                "kind": "official_x",
                "published_at": created_at
            }
        return None

    @staticmethod
    def _within_window(created_at, since_dt):
        try:
            when = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            return True  # can't parse the timestamp: don't block on it
        return when >= since_dt
