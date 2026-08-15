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
            if not text or not contains_here_we_go(text): continue
            link = node.select_one("a.tgme_widget_message_date")
            url = link.get("href") if link else None
            if url:
                out.append({
                    "url": url,
                    "text": text,
                    "discovered_at": datetime.now(timezone.utc).isoformat()
                })
        return out
