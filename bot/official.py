import calendar
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urljoin, urlparse
import requests, feedparser
from bs4 import BeautifulSoup
from .normalize import clean_text, name_match
from .clubs import find_club

# Words that need to appear near the player's name for a mention to count
# as transfer evidence. Guards against an old "Former Arsenal player X..."
# style article, or an unrelated mention of the player, being mistaken for
# an announcement. Deliberately broad (covers signing, official, loan,
# medical-passed style wording) since official club copy varies a lot.
_TRANSFER_KEYWORDS = re.compile(
    r"\b(sign(?:s|ed|ing)?|join(?:s|ed|ing)?|official|confirm(?:s|ed)?|"
    r"complet(?:e|es|ed|ion)|welcome|unveil(?:s|ed)?|deal|transfer|"
    r"loan|permanent|medical|contract)\b",
    re.I,
)


class OfficialVerifier:
    def __init__(self, clubs, timeout=20, user_agent="TransferConfirmationBot/4.0", google_news=True,
                 x_verifier=None, instagram_verifier=None, max_age_hours=24):
        self.clubs = clubs
        self.timeout = timeout
        self.google_news = google_news
        self.x_verifier = x_verifier
        self.instagram_verifier = instagram_verifier
        self.headers = {"User-Agent": user_agent}
        # Applied to feed/Google News entries that carry a publish date.
        # Site homepage scraping has no reliable per-link date, so it
        # relies on the keyword check instead (see _is_transfer_mention).
        self.max_age_hours = max_age_hours

    def verify(self, player, to_club):
        if not player or not to_club:
            return None
        club = self.find_club(to_club)
        if not club:
            return None

        # Social APIs are checked before web discovery because they directly
        # represent the configured official account.
        if self.x_verifier:
            hit = self.x_verifier.latest_match(
                club.get("x_user_id"), player,
                [club.get("name","")] + club.get("aliases", [])
            )
            if hit:
                return hit

        if self.instagram_verifier:
            hit = self.instagram_verifier.latest_match(
                club.get("instagram_username"), player,
                [club.get("name","")] + club.get("aliases", [])
            )
            if hit:
                return hit

        for feed_url in club.get("official_feeds", []):
            hit = self._feed(feed_url, player, club)
            if hit:
                return hit

        domain = club.get("domain")
        if domain:
            hit = self._site(domain, player, club)
            if hit:
                return hit

            if self.google_news:
                hit = self._google_news(player, club)
                if hit:
                    return hit
        return None

    def find_club(self, name):
        return find_club(self.clubs, name)

    def _feed(self, url, player, club):
        feed = feedparser.parse(url)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.max_age_hours)
        for entry in feed.entries[:50]:
            if not self._entry_recent_enough(entry, cutoff):
                continue
            blob = clean_text(f'{entry.get("title","")} {entry.get("summary","")}')
            if self._is_transfer_mention(player, blob):
                return {
                    "url": entry.get("link", url),
                    "source": club["name"],
                    "kind": "official_feed"
                }
        return None

    def _site(self, domain, player, club):
        base = domain if domain.startswith("http") else "https://" + domain
        r = requests.get(base, headers=self.headers, timeout=self.timeout, allow_redirects=True)
        r.raise_for_status()
        host = self._host(r.url)
        soup = BeautifulSoup(r.text, "html.parser")

        for a in soup.select("a[href]"):
            label = clean_text(a.get_text(" ", strip=True))
            href = a.get("href", "")
            # No reliable per-link publish date on a homepage scrape, so
            # the transfer-keyword requirement is what stops a stale
            # "related articles" link (e.g. an old profile page) from
            # counting as evidence here.
            if not self._is_transfer_mention(player, label):
                continue
            absolute = self._absolute(r.url, href)
            if self._host(absolute) == host:
                return {"url": absolute, "source": club["name"], "kind": "official_site"}
        return None

    def _google_news(self, player, club):
        host = self._host(club["domain"])
        query = quote(f'"{player}" site:{host}')
        rss = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(rss)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.max_age_hours)

        for entry in feed.entries[:20]:
            if not self._entry_recent_enough(entry, cutoff):
                continue
            candidate = entry.get("link", "")
            if not candidate:
                continue
            final_url = self._resolve(candidate)
            if self._host(final_url) != host:
                continue
            if self._is_transfer_mention(player, f'{entry.get("title","")} {entry.get("summary","")}'):
                return {
                    "url": final_url,
                    "source": club["name"],
                    "kind": "official_domain_discovery"
                }
        return None

    def _resolve(self, url):
        try:
            r = requests.get(url, headers=self.headers, timeout=self.timeout,
                             allow_redirects=True, stream=True)
            return r.url
        except requests.RequestException:
            return url

    @staticmethod
    def _absolute(base, href):
        return urljoin(base, href)

    @staticmethod
    def _is_transfer_mention(player, text):
        """A mention only counts as evidence if the player's name AND a
        transfer-related action word both appear — this stops an old
        unrelated article (e.g. "Former Arsenal player X now at...") from
        being read as today's confirmation.
        """
        return name_match(player, text) and bool(_TRANSFER_KEYWORDS.search(text))

    @staticmethod
    def _entry_recent_enough(entry, cutoff):
        """Returns True if the entry's publish date is within the window,
        OR if no parseable date is available at all (feeds vary a lot in
        whether they expose one — we don't want to silently discard every
        result just because a particular feed omits dates). When a date
        IS present, it must be recent — this is what stops a months-old
        feed entry from confirming a brand new transfer.
        """
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if not parsed:
            return True
        when = datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
        return when >= cutoff

    @staticmethod
    def _host(url):
        return urlparse(url).netloc.lower().split(":")[0].removeprefix("www.")
