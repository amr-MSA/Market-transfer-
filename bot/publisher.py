import time
import requests


class TelegramPublisher:
    """Sends the same message to one or many channels using a single bot token.

    One analysis/verification cycle produces one message; this class fans it
    out to every enabled channel in config/channels.json. A failure on one
    channel (bot removed, lost admin rights, etc.) is logged and skipped —
    it must never stop delivery to the remaining channels.
    """

    def __init__(self, token, channels, timeout=20, send_delay_seconds=0.35):
        self.token = token
        # channels: list of {"id": str, "name": str, "enabled": bool}
        self.channels = channels
        self.timeout = timeout
        # small delay between sends to stay safely under Telegram's
        # per-chat rate limit when fanning out to many channels
        self.send_delay_seconds = send_delay_seconds

    def _send_to_chat(self, chat_id, text, image_url=None):
        if image_url and len(text) <= 1024:
            endpoint = f"https://api.telegram.org/bot{self.token}/sendPhoto"
            payload = {
                "chat_id": chat_id,
                "photo": image_url,
                "caption": text,
                "parse_mode": "HTML",
            }
        else:
            endpoint = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            }
        r = requests.post(endpoint, json=payload, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(data)
        return data

    def send(self, text, channels=None, image_url=None):
        """Send text to channels (default: every enabled channel).

        Pass an explicit `channels` subset to retry delivery only to
        channels that failed in a previous cycle, instead of re-sending
        to channels that already succeeded.

        Returns a per-channel result summary so callers can inspect/log
        failures without crashing the run.
        """
        targets = channels if channels is not None else [c for c in self.channels if c.get("enabled", True)]
        results = []
        for i, channel in enumerate(targets):
            chat_id = channel["id"]
            name = channel.get("name", chat_id)
            try:
                if image_url:
                    data = self._send_to_chat(chat_id, text, image_url=image_url)
                else:
                    data = self._send_to_chat(chat_id, text)
                results.append({"channel": name, "id": chat_id, "ok": True, "response": data})
            except Exception as e:
                # Do not raise: one broken channel (bot kicked, no admin
                # rights, wrong id, etc.) must not block the rest.
                results.append({"channel": name, "id": chat_id, "ok": False, "error": str(e)})

            if i < len(targets) - 1 and self.send_delay_seconds:
                time.sleep(self.send_delay_seconds)

        return results
