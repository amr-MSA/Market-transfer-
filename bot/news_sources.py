import html
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import feedparser


class FootballNewsSource:
    """Fetch recent football RSS items from configured sources."""

    def __init__(self, sources, timeout=20, user_agent="TransferBot/1.0", max_age_hours=2):
        self.sources = sources
        self.timeout = timeout
        self.user_agent = user_agent
        self.max_age = timedelta(hours=max_age_hours)

    def fetch(self):
        now = datetime.now(timezone.utc)
        results = []
        seen_urls = set()

        for source in self.sources:
            if not source.get("enabled", True):
                continue

            url = source.get("url")
            if not url:
                continue

            try:
                feed = feedparser.parse(
                    url,
                    agent=self.user_agent,
                )
            except Exception as exc:
                print(f"[news-source] {source.get('name', url)} failed: {exc}")
                continue

            if getattr(feed, "bozo", False) and not feed.entries:
                print(f"[news-source] {source.get('name', url)} returned no entries")
                continue

            try:
                max_items = max(1, int(source.get("max_items", 12)))
            except (TypeError, ValueError):
                max_items = 12

            for entry in feed.entries[:max_items]:
                link = (entry.get("link") or "").strip()
                if not link or link in seen_urls:
                    continue

                published = self._entry_time(entry)
                if published is None:
                    published = now

                if now - published > self.max_age:
                    continue
                if published > now + timedelta(minutes=10):
                    continue

                title = self._clean(entry.get("title", ""))
                summary = self._clean(entry.get("summary", entry.get("description", "")))

                if not title:
                    continue

                seen_urls.add(link)
                results.append({
                    "id": link,
                    "title": title,
                    "summary": summary,
                    "url": link,
                    "source": source.get("name") or self._host(link),
                    "published_at": published.isoformat(),
                })

        results.sort(key=lambda x: x["published_at"], reverse=True)
        return results

    @staticmethod
    def _entry_time(entry):
        for key in ("published_parsed", "updated_parsed"):
            value = entry.get(key)
            if value:
                try:
                    import calendar
                    return datetime.fromtimestamp(
                        calendar.timegm(value),
                        tz=timezone.utc,
                    )
                except (TypeError, ValueError, OverflowError):
                    pass
        return None

    @staticmethod
    def _clean(value):
        value = html.unescape(re.sub(r"<[^>]+>", " ", value or ""))
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _host(url):
        return urlparse(url).netloc
