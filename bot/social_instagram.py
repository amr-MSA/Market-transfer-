import requests
from datetime import datetime, timedelta, timezone
from .normalize import clean_text, name_match

# Graph API version isolated in one place rather than hard-coded inline,
# so bumping it later is a one-line change.
_GRAPH_API_VERSION = "v24.0"


class InstagramVerifier:
    """Checks public posts of configured Instagram Professional accounts.

    Uses Meta's Business Discovery API. It is intentionally disabled unless
    both an access token and the bot/app's Instagram user ID are configured.
    """

    def __init__(self, access_token, app_ig_user_id, timeout=20, max_age_hours=24):
        self.token = access_token
        self.app_ig_user_id = app_ig_user_id
        self.timeout = timeout
        self.max_age_hours = max_age_hours

    def latest_match(self, username, player, club_aliases):
        if not self.token or not self.app_ig_user_id or not username:
            return None

        fields = (
            f"business_discovery.username({username})"
            "{username,media.limit(20){caption,permalink,timestamp}}"
        )
        r = requests.get(
            f"https://graph.facebook.com/{_GRAPH_API_VERSION}/{self.app_ig_user_id}",
            params={"fields": fields, "access_token": self.token},
            timeout=self.timeout
        )
        r.raise_for_status()
        account = r.json().get("business_discovery", {})

        # Business Discovery has no server-side time filter, so recency
        # must be enforced client-side: a months-old post about this
        # player must never be treated as confirming today's transfer.
        since_dt = datetime.now(timezone.utc) - timedelta(hours=self.max_age_hours)

        for post in account.get("media", {}).get("data", []):
            timestamp = post.get("timestamp")
            if timestamp and not self._within_window(timestamp, since_dt):
                continue
            caption = clean_text(post.get("caption", ""))
            if not name_match(player, caption):
                continue
            if not any(name_match(alias, caption) for alias in club_aliases if alias):
                continue
            return {
                "url": post.get("permalink"),
                "source": "official_instagram",
                "kind": "official_instagram",
                "published_at": timestamp
            }
        return None

    @staticmethod
    def _within_window(timestamp, since_dt):
        try:
            when = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return True  # can't parse the timestamp: don't block on it
        return when >= since_dt
