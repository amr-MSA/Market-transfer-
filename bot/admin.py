import json
import os
from pathlib import Path

import requests


class TelegramAdmin:
    """Small command/control layer for GitHub Actions polling.

    GitHub Actions is not a permanent process, so this polls getUpdates once
    per workflow run and persists the update offset in data/bot_updates.json.
    """

    def __init__(self, token, admin_ids, channels_path, state_path, updates_path, timeout=20):
        self.token = token
        self.admin_ids = {str(x).strip() for x in admin_ids if str(x).strip()}
        self.channels_path = Path(channels_path)
        self.state_path = Path(state_path)
        self.updates_path = Path(updates_path)
        self.timeout = timeout
        self.api = f"https://api.telegram.org/bot{token}"

    def _api(self, method, payload=None):
        r = requests.post(f"{self.api}/{method}", json=payload or {}, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(data)
        return data.get("result")

    def _load_updates(self):
        if not self.updates_path.exists():
            return {"offset": 0, "addchannel_mode": False}
        try:
            with self.updates_path.open(encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {"offset": 0, "addchannel_mode": False}
            data.setdefault("addchannel_mode", False)
            return data
        except (OSError, ValueError):
            return {"offset": 0, "addchannel_mode": False}

    def _save_updates(self, data):
        self.updates_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.updates_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, self.updates_path)

    def _load_channels(self):
        with self.channels_path.open(encoding="utf-8") as f:
            return json.load(f)

    def _save_channels(self, data):
        tmp = self.channels_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, self.channels_path)

    def _send(self, chat_id, text):
        return self._api("sendMessage", {"chat_id": chat_id, "text": text})

    def _admin(self, user_id):
        return str(user_id) in self.admin_ids

    def _forwarded_channel(self, message):
        # Telegram's current Bot API uses forward_origin for forwarded posts.
        origin = message.get("forward_origin") or {}
        if origin.get("type") == "channel":
            chat = origin.get("chat") or {}
            if chat.get("id") is not None:
                return {"id": str(chat["id"]), "name": chat.get("title") or str(chat["id"])}

        # Compatibility with older Telegram message payloads.
        old = message.get("forward_from_chat") or {}
        if old.get("id") is not None and old.get("type") == "channel":
            return {"id": str(old["id"]), "name": old.get("title") or str(old["id"])}
        return None

    def _add_channel(self, channel):
        data = self._load_channels()
        channels = data.setdefault("channels", [])
        for existing in channels:
            if str(existing.get("id")) == str(channel["id"]):
                existing["enabled"] = True
                if channel.get("name"):
                    existing["name"] = channel["name"]
                self._save_channels(data)
                return False
        channels.append({"id": channel["id"], "name": channel["name"], "enabled": True})
        self._save_channels(data)
        return True

    def _health(self):
        channels = self._load_channels().get("channels", [])
        enabled = [c for c in channels if c.get("enabled", True)]
        state_ok = self.state_path.exists()
        return (
            "🤖 Transfer Bot Health\n\n"
            "✅ Telegram API reachable\n"
            f"{'✅' if state_ok else '⚠️'} State file: {'OK' if state_ok else 'not created yet'}\n"
            f"📢 Enabled channels: {len(enabled)}\n"
            "⚙️ GitHub Actions: running on schedule\n\n"
            "Use /testchannel to test Telegram delivery."
        )

    def _test_parser(self):
        # This deliberately stays independent of Fabrizio and live transfers.
        from .parser import parse_transfer
        sample = "HERE WE GO! Test Player to Test United."
        parsed = parse_transfer(sample)
        return (
            "🧪 Parser test\n\n"
            f"Player: {parsed.get('player') or 'not detected'}\n"
            f"To club: {parsed.get('to_club') or 'not detected'}\n\n"
            "This test does not write to transfer state."
        )

    def process(self, publisher):
        """Process pending Telegram updates and return a short run summary."""
        updates_state = self._load_updates()
        offset = int(updates_state.get("offset", 0) or 0)
        updates = self._api("getUpdates", {"offset": offset, "timeout": 1, "allowed_updates": ["message"]})
        if not updates:
            return "no updates"

        processed = 0
        for update in updates:
            update_id = int(update["update_id"])
            updates_state["offset"] = update_id + 1
            message = update.get("message") or {}
            user = message.get("from") or {}
            user_id = user.get("id")
            if user_id is None or not self._admin(user_id):
                processed += 1
                continue

            text = (message.get("text") or "").strip()
            chat_id = message.get("chat", {}).get("id")

            addchannel_mode = bool(updates_state.get("addchannel_mode", False))

            if text == "/myid":
                self._send(chat_id, f"🆔 Your Telegram ID is:\n{user_id}")
            elif text == "/health":
                self._send(chat_id, self._health())
            elif text == "/test":
                self._send(chat_id, self._test_parser())
            elif text == "/testchannel":
                results = publisher.send("🧪 Transfer Bot Test\n\nTelegram delivery is working correctly.")
                ok = sum(1 for r in results if r["ok"])
                total = len(results)
                self._send(chat_id, f"🧪 Channel test complete: {ok}/{total} channels succeeded.")
            elif text == "/addchannel":
                updates_state["addchannel_mode"] = True
                self._send(chat_id, "➕ Add-channel mode enabled. Forward one post from the target channel to me.")
            elif text == "/cancel":
                updates_state["addchannel_mode"] = False
                self._send(chat_id, "🛑 Add-channel mode cancelled.")
            elif text.startswith("/"):
                self._send(chat_id, "Commands: /myid /health /test /testchannel /addchannel /cancel")
            else:
                channel = self._forwarded_channel(message)
                if channel and addchannel_mode:
                    added = self._add_channel(channel)
                    updates_state["addchannel_mode"] = False
                    status = "added" if added else "already existed; enabled"
                    self._send(chat_id, f"✅ Channel {status}.\n\nName: {channel['name']}\nID: {channel['id']}")
                else:
                    self._send(chat_id, "ℹ️ Use /addchannel first, then forward one post from the target channel.")
            processed += 1

        self._save_updates(updates_state)
        return f"processed {processed} update(s)"
