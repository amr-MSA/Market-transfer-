import json
import os
import re
import shlex
from pathlib import Path

import requests
from .content_types import ALL, CONTENT_TYPES, normalize_content_types


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

    @staticmethod
    def _normalize_channel_id(value):
        value = str(value or "").strip()
        if re.fullmatch(r"-?\d+", value):
            return value
        if re.fullmatch(r"@[A-Za-z0-9_]{5,}", value):
            return value
        return None

    def _add_channel(self, channel):
        channel_id = self._normalize_channel_id(channel.get("id"))
        if not channel_id:
            raise ValueError("Invalid channel ID. Use a numeric ID such as -1001234567890 or a public @username.")

        data = self._load_channels()
        channels = data.setdefault("channels", [])
        for existing in channels:
            if str(existing.get("id")) == channel_id:
                existing["enabled"] = True
                if channel.get("name"):
                    existing["name"] = channel["name"]
                self._save_channels(data)
                return False
        channels.append({
            "id": channel_id,
            "name": channel.get("name") or channel_id,
            "enabled": True,
            "content_types": [ALL],
        })
        self._save_channels(data)
        return True

    def _set_channel_types(self, channel_id, values):
        channel_id = self._normalize_channel_id(channel_id)
        if not channel_id:
            raise ValueError("Invalid channel ID.")
        content_types = normalize_content_types(values)
        data = self._load_channels()
        for channel in data.get("channels", []):
            if str(channel.get("id")) == channel_id:
                channel["content_types"] = content_types
                self._save_channels(data)
                return content_types
        return None

    def _set_channel_enabled(self, channel_id, enabled):
        channel_id = self._normalize_channel_id(channel_id)
        if not channel_id:
            raise ValueError("Invalid channel ID.")
        data = self._load_channels()
        for channel in data.get("channels", []):
            if str(channel.get("id")) == channel_id:
                channel["enabled"] = enabled
                self._save_channels(data)
                return True
        return False

    def _remove_channel(self, channel_id):
        channel_id = self._normalize_channel_id(channel_id)
        if not channel_id:
            raise ValueError("Invalid channel ID.")
        data = self._load_channels()
        before = len(data.get("channels", []))
        data["channels"] = [c for c in data.get("channels", []) if str(c.get("id")) != channel_id]
        if len(data["channels"]) == before:
            return False
        self._save_channels(data)
        return True

    def _list_channels(self):
        channels = self._load_channels().get("channels", [])
        if not channels:
            return "📢 No channels configured.\n\nUse /addchannel <channel_id> [name]."
        lines = ["📢 Configured channels:"]
        for channel in channels:
            status = "enabled" if channel.get("enabled", True) else "disabled"
            subscriptions = channel.get("content_types") or [ALL]
            types = "الكل" if ALL in subscriptions else "، ".join(subscriptions)
            lines.append(f"• {channel.get('name') or channel.get('id')} — {channel.get('id')} — {status}\n  الأنواع: {types}")
        return "\n".join(lines)

    @staticmethod
    def _command_parts(text):
        try:
            parts = shlex.split(text)
        except ValueError:
            return [], ""
        if not parts:
            return [], ""
        command = parts[0].split("@", 1)[0].lower()
        return parts[1:], command

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
            args, command = self._command_parts(text)
            addchannel_mode = bool(updates_state.get("addchannel_mode", False))

            if command == "/myid":
                self._send(chat_id, f"🆔 Your Telegram ID is:\n{user_id}")
            elif command == "/health":
                self._send(chat_id, self._health())
            elif command == "/test":
                self._send(chat_id, self._test_parser())
            elif command == "/testchannel":
                results = publisher.send("🧪 Transfer Bot Test\n\nTelegram delivery is working correctly.")
                ok = sum(1 for r in results if r["ok"])
                total = len(results)
                self._send(chat_id, f"🧪 Channel test complete: {ok}/{total} channels succeeded.")
            elif command == "/channels":
                self._send(chat_id, self._list_channels())
            elif command == "/types":
                self._send(
                    chat_id,
                    "أنواع المحتوى المدعومة:\n" + "، ".join(CONTENT_TYPES) +
                    "\n\nاستخدم: /settypes <channel_id> انتقال,إعارة,هدف\n"
                    "أو: /settypes <channel_id> الكل"
                )
            elif command == "/addchannel":
                if not args:
                    updates_state["addchannel_mode"] = True
                    self._send(
                        chat_id,
                        "➕ أرسل المعرّف مباشرة بهذا الشكل:\n/addchannel -1001234567890 اسم القناة\n"
                        "أو لقناة عامة:\n/addchannel @channel_username اسم القناة\n\n"
                        "ويمكنك أيضًا إعادة توجيه منشور كطريقة احتياطية."
                    )
                else:
                    try:
                        channel_id = args[0]
                        name = " ".join(args[1:]).strip() or channel_id
                        added = self._add_channel({"id": channel_id, "name": name})
                        updates_state["addchannel_mode"] = False
                        status = "تمت الإضافة والتفعيل" if added else "كانت موجودة وتم تفعيلها"
                        self._send(chat_id, f"✅ {status}.\n\nالاسم: {name}\nالمعرّف: {channel_id}")
                    except ValueError as exc:
                        self._send(chat_id, f"❌ {exc}")
            elif command in {"/removechannel", "/disablechannel", "/enablechannel"}:
                if len(args) != 1:
                    self._send(chat_id, f"ℹ️ الاستخدام: {command} <channel_id>")
                else:
                    try:
                        if command == "/removechannel":
                            changed = self._remove_channel(args[0])
                            action = "حُذفت" if changed else "غير موجودة"
                        else:
                            changed = self._set_channel_enabled(args[0], command == "/enablechannel")
                            action = "فُعّلت" if command == "/enablechannel" and changed else "عُطّلت" if changed else "غير موجودة"
                        self._send(chat_id, f"✅ القناة {action}.")
                    except ValueError as exc:
                        self._send(chat_id, f"❌ {exc}")
            elif command == "/settypes":
                if len(args) < 2:
                    self._send(
                        chat_id,
                        "ℹ️ الاستخدام: /settypes <channel_id> انتقال,إعارة,هدف\n"
                        "للاشتراك بكل الأخبار: /settypes <channel_id> الكل"
                    )
                else:
                    try:
                        content_types = self._set_channel_types(args[0], " ".join(args[1:]))
                        if content_types is None:
                            self._send(chat_id, "❌ القناة غير موجودة.")
                        else:
                            display = "الكل" if ALL in content_types else "، ".join(content_types)
                            self._send(chat_id, f"✅ تم تحديث أنواع المحتوى: {display}")
                    except ValueError as exc:
                        self._send(chat_id, f"❌ {exc}\nاستخدم /types لعرض الخيارات.")
            elif command == "/cancel":
                updates_state["addchannel_mode"] = False
                self._send(chat_id, "🛑 تم إلغاء وضع إضافة القناة.")
            elif command.startswith("/"):
                self._send(
                    chat_id,
                    "الأوامر: /myid /health /test /testchannel /channels /types /addchannel "
                    "/settypes /removechannel /enablechannel /disablechannel /cancel"
                )
            else:
                channel = self._forwarded_channel(message)
                if channel and addchannel_mode:
                    try:
                        added = self._add_channel(channel)
                        updates_state["addchannel_mode"] = False
                        status = "تمت الإضافة" if added else "كانت موجودة وتم تفعيلها"
                        self._send(chat_id, f"✅ {status}.\n\nالاسم: {channel['name']}\nالمعرّف: {channel['id']}")
                    except ValueError as exc:
                        self._send(chat_id, f"❌ {exc}")
                else:
                    self._send(chat_id, "ℹ️ استخدم /addchannel <channel_id> [name] لإضافة قناة مباشرة.")
            processed += 1

        self._save_updates(updates_state)
        return f"processed {processed} update(s)"
