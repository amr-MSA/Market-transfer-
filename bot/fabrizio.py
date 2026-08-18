import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from .normalize import clean_text, contains_here_we_go


class FabrizioSource:
    def __init__(self, url, timeout=20, user_agent="TransferConfirmationBot/2.0"):
        self.url, self.timeout = url, timeout
        self.headers = {"User-Agent": user_agent}

    def fetch(self):
        r = requests.get(self.url, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        nodes = soup.select(".tgme_widget_message_wrap")
        out = []
        for node in nodes:
            text_node = node.select_one(".tgme_widget_message_text")
            text = clean_text(text_node.get_text(" ", strip=True) if text_node else "")
            if not text or not contains_here_we_go(text):
                continue
            link = node.select_one("a.tgme_widget_message_date")
            url = link.get("href") if link else None
            if not url:
                continue

            date_node = node.select_one(".tgme_widget_message_date")
            published_at = None
            if date_node and date_node.get("datetime"):
                try:
                    published_at = datetime.fromisoformat(
                        date_node["datetime"].replace("Z", "+00:00")
                    ).astimezone(timezone.utc).isoformat()
                except ValueError:
                    published_at = None

            # Telegram's public widget normally exposes the message timestamp
            # as datetime on the date link. Keep discovery time only as a
            # fallback; expiry logic must prefer the actual post time.
            out.append({
                "url": url,
                "text": text,
                "published_at": published_at,
                "discovered_at": datetime.now(timezone.utc).isoformat(),
            })
        return out
