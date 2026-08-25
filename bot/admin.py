import json
import os
import re
import shlex
from pathlib import Path

import requests
from .content_types import ALL, CONTENT_TYPES, normalize_content_types
from .identity_cards import IdentityCardRegistry, TelegramIdentityCards
from .identity_resolver import IdentityResolver, WikidataIdentitySource, ambiguity_report, normalize_name
from .media_library import MediaLibrary, TelegramMediaArchive


ROOT = Path(__file__).resolve().parents[1]


class TelegramAdmin:
    """Small command/control layer for GitHub Actions polling.

    GitHub Actions is not a permanent process, so this polls getUpdates once
    per workflow run and persists the update offset in data/bot_updates.json.
    """

    def __init__(self, token, admin_ids, channels_path, state_path, updates_path, timeout=20, settings_path=None):
        self.token = token
        self.admin_ids = {str(x).strip() for x in admin_ids if str(x).strip()}
        self.channels_path = Path(channels_path)
        self.state_path = Path(state_path)
        self.updates_path = Path(updates_path)
        self.settings_path = Path(settings_path) if settings_path else None
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
            return {"offset": 0, "addchannel_mode": False, "media_library_mode": False, "identity_cards_mode": False, "manual_media": None}
        try:
            with self.updates_path.open(encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {"offset": 0, "addchannel_mode": False, "media_library_mode": False, "identity_cards_mode": False, "manual_media": None}
            data.setdefault("addchannel_mode", False)
            data.setdefault("media_library_mode", False)
            data.setdefault("identity_cards_mode", False)
            data.setdefault("manual_media", None)
            return data
        except (OSError, ValueError):
            return {"offset": 0, "addchannel_mode": False, "media_library_mode": False, "identity_cards_mode": False, "manual_media": None}

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

    def _load_settings(self):
        if not self.settings_path or not self.settings_path.exists():
            return {}
        try:
            with self.settings_path.open(encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_settings(self, data):
        if not self.settings_path:
            raise RuntimeError("Media library settings are unavailable.")
        tmp = self.settings_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp, self.settings_path)

    def _send(self, chat_id, text):
        return self._api("sendMessage", {"chat_id": chat_id, "text": text})

    def report_identity_ambiguity(self, name, entity_type, organization, candidates):
        text = ambiguity_report(name, entity_type, organization, candidates)
        for admin_id in self.admin_ids:
            try:
                self._send(admin_id, text)
            except (RuntimeError, requests.RequestException):
                continue

    @staticmethod
    def _help_message():
        return (
            "🤖 لوحة تحكم البوت\n\n"
            "أرسل أي أمر أدناه وسيرد البوت بالنتيجة أو بالخطوة التالية.\n\n"
            "📡 القنوات والنشر\n"
            "• /addchannel <رابط القناة> — إضافة قناة عامة للنشر.\n"
            "• /channels — عرض القنوات وحالتها.\n"
            "• /settypes <معرف القناة> <الأنواع> — تحديد الأخبار المسموح بها.\n"
            "• /types — عرض أنواع المحتوى.\n"
            "• /enablechannel أو /disablechannel أو /removechannel <معرف القناة> — إدارة قناة.\n\n"
            "🖼 مكتبة الصور والهوية\n"
            "• /setmedialibrary — ربط قناة الصور الخاصة.\n"
            "• /medialibrary — عرض حالة مكتبة الصور.\n"
            "• /setidentitylibrary — ربط قناة بطاقات الهوية.\n"
            "• /identitycards — عرض حالة بطاقات الهوية.\n"
            "• /addmedia — بدء إضافة صورة موثقة يدويًا.\n\n"
            "🧪 الفحص والمساعدة\n"
            "• /health — حالة البوت والتشغيل.\n"
            "• /testchannel — اختبار الإرسال إلى القنوات.\n"
            "• /test — اختبار تحليل نموذج انتقال.\n"
            "• /myid — إظهار معرف Telegram الخاص بك.\n"
            "• /cancel — إلغاء العملية الحالية.\n\n"
            "⚠️ عند التباس اسم لاعب أو مدرب، يرسل البوت تلقائيًا تقريرًا بالمرشحين ومفاتيح Wikidata للمدراء."
        )

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

    @staticmethod
    def _public_channel_reference(value):
        value = str(value or "").strip()
        if re.fullmatch(r"@[A-Za-z0-9_]{5,}", value):
            return value
        match = re.fullmatch(r"https?://(?:t\.me|telegram\.me)/([A-Za-z0-9_]{5,})/?", value, flags=re.IGNORECASE)
        return f"@{match.group(1)}" if match else None

    def _resolve_public_channel(self, value):
        reference = self._public_channel_reference(value)
        if not reference:
            raise ValueError("استخدم رابط قناة عامة صحيحًا مثل https://t.me/channel_name. أما القناة الخاصة فأعد توجيه منشور منها.")
        chat = self._api("getChat", {"chat_id": reference}) or {}
        if chat.get("type") != "channel" or chat.get("id") is None:
            raise ValueError("الرابط لا يشير إلى قناة Telegram عامة.")
        me = self._api("getMe") or {}
        membership = self._api("getChatMember", {"chat_id": chat["id"], "user_id": me.get("id")}) or {}
        if membership.get("status") not in {"administrator", "creator"} or membership.get("can_post_messages") is False:
            raise ValueError("أضف البوت مشرفًا في القناة بصلاحية نشر الرسائل أولًا.")
        return {"id": str(chat["id"]), "name": chat.get("title") or reference}

    def _channel_from_input(self, value, name=None):
        reference = self._public_channel_reference(value)
        if reference:
            channel = self._resolve_public_channel(value)
            if name:
                channel["name"] = name
            return channel
        channel_id = self._normalize_channel_id(value)
        if not channel_id:
            raise ValueError("استخدم رابطًا عامًا أو معرف قناة رقميًا. للقنوات الخاصة، أعد توجيه منشور منها.")
        return {"id": channel_id, "name": name or channel_id}

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

    def _set_media_library(self, channel):
        channel_id = self._normalize_channel_id(channel.get("id"))
        if not channel_id:
            raise ValueError("Invalid library channel ID.")
        settings = self._load_settings()
        settings["media_library_enabled"] = True
        settings["media_library_auto_archive"] = True
        settings["media_library_channel_id"] = channel_id
        settings["media_library_channel_name"] = channel.get("name") or channel_id
        self._save_settings(settings)
        return settings["media_library_channel_name"], channel_id

    def _set_identity_cards_library(self, channel):
        channel_id = self._normalize_channel_id(channel.get("id"))
        if not channel_id:
            raise ValueError("Invalid identity-cards channel ID.")
        settings = self._load_settings()
        settings["identity_cards_enabled"] = True
        settings["identity_cards_channel_id"] = channel_id
        settings["identity_cards_channel_name"] = channel.get("name") or channel_id
        self._save_settings(settings)
        return settings["identity_cards_channel_name"], channel_id

    def _media_library_status(self):
        settings = self._load_settings()
        channel_id = settings.get("media_library_channel_id")
        if not channel_id:
            return "🗂 مكتبة الصور: غير مربوطة بعد. استخدم /setmedialibrary ثم أعد توجيه منشور من القناة الخاصة."
        return (
            "🗂 مكتبة الصور: مفعّلة\n"
            f"القناة: {settings.get('media_library_channel_name') or channel_id}\n"
            f"المعرّف: {channel_id}\n"
            "الحفظ التلقائي: مفعّل"
        )

    def _identity_cards_status(self):
        settings = self._load_settings()
        channel_id = settings.get("identity_cards_channel_id")
        if not channel_id:
            return "🪪 قناة بطاقات الهوية: غير مربوطة بعد. استخدم /setidentitylibrary."
        return (
            "🪪 بطاقات الهوية: مفعّلة\n"
            f"القناة: {settings.get('identity_cards_channel_name') or channel_id}\n"
            f"المعرّف: {channel_id}"
        )

    @staticmethod
    def _manual_media_context(args):
        if len(args) not in {6, 7}:
            raise ValueError(
                'الاستخدام: /addmedia "اسم الشخص" player "النادي أو -" "السنة أو -" "رابط المصدر" "الرخصة" [wikidata:Q...]'
            )
        person, raw_type, raw_club, raw_year, source_url, license_name, *identity_key = args
        entity_type = {"player": "player", "لاعب": "player", "manager": "manager", "مدرب": "manager"}.get(raw_type.casefold())
        if not entity_type:
            raise ValueError("النوع يجب أن يكون player أو manager.")
        club = None if raw_club.strip().casefold() in {"-", "generic", "عام"} else raw_club.strip()
        year = None if raw_year.strip() == "-" else raw_year.strip()
        if club and (not year or not year.isdigit() or not 1850 <= int(year) <= 2200):
            raise ValueError("صورة النادي تحتاج سنة بداية صحيحة من أربعة أرقام.")
        if not club and year:
            raise ValueError("استخدم - للسنة عندما تكون الصورة عامة بلا نادٍ.")
        if not source_url.startswith(("https://", "http://")):
            raise ValueError("أدخل رابط المصدر الكامل للصورة.")
        if len(license_name.strip()) < 2:
            raise ValueError("أدخل الرخصة أو وصفًا واضحًا لحق الاستخدام.")
        selected_key = identity_key[0].strip() if identity_key else None
        if selected_key and not re.fullmatch(r"wikidata:Q\d+", selected_key):
            raise ValueError("المعرف المرجعي يجب أن يكون بالصيغة wikidata:Q123.")
        return {
            "person": person.strip(),
            "entity_type": entity_type,
            "club": club,
            "start_year": int(year) if year else None,
            "source_url": source_url.strip(),
            "license": license_name.strip(),
            "identity_key": selected_key,
        }

    def _archive_manual_media(self, file_id, context):
        settings = self._load_settings()
        channel_id = settings.get("media_library_channel_id")
        if not channel_id:
            raise ValueError("اربط قناة المكتبة أولًا عبر /setmedialibrary.")
        library = MediaLibrary(ROOT / settings.get("media_library_path", "data/media_library.json"))
        data = library.load()
        registry = IdentityCardRegistry(ROOT / settings.get("identity_cards_path", "data/identity_cards.json"))
        registry_data = registry.load()
        source = WikidataIdentitySource(self.timeout, settings.get("user_agent", "TransferConfirmationBot/5.0"))
        if context.get("identity_key"):
            facts = source.facts_for_identity_key(context["identity_key"], context["entity_type"])
            if not facts or normalize_name(facts.get("canonical_name")) != normalize_name(context["person"]):
                raise ValueError("المعرف المرجعي لا يطابق الاسم المدخل أو تعذر التحقق منه.")
            existing = registry.find_person_by_identity_key(registry_data, facts["identity_key"])
            decision = {"status": "EXISTING" if existing else "CREATE_VERIFIED", "card": existing, "facts": facts}
        else:
            decision = IdentityResolver(registry, source).resolve(
                registry_data,
                context["person"],
                context["entity_type"],
                organization=context.get("club"),
            )
        if decision["status"] in {"AMBIGUOUS", "NOT_FOUND"}:
            if decision["status"] == "AMBIGUOUS":
                raise ValueError(ambiguity_report(
                    context["person"],
                    context["entity_type"],
                    context.get("club"),
                    decision.get("candidates") or [],
                ))
            raise ValueError("تعذر العثور على هوية مرجعية مؤكدة. لم تُحفظ الصورة؛ راجع الاسم أو استخدم identity_key موثوقًا.")

        known_card = decision.get("card")
        person_id = known_card.get("person_id") if known_card else None
        person, club, stint, asset_id = library.reserve_contextual_ids(
            data,
            context["person"],
            context["entity_type"],
            context.get("club"),
            context.get("start_year"),
            person_id=person_id,
        )
        person_card = registry.ensure_person(registry_data, person)
        facts = decision.get("facts")
        if facts:
            registry.apply_facts(registry_data, person_card, facts)
        registry.save(registry_data)
        archive = TelegramMediaArchive(self.token, channel_id, self.timeout)
        result = archive.archive_manual(
            file_id,
            person,
            asset_id,
            context["license"],
            club,
            stint,
        )
        if not result or not result.get("file_id"):
            raise ValueError("تعذر حفظ الصورة في قناة المكتبة. تحقق من صلاحية نشر الرسائل للبوت.")
        media = MediaLibrary.manual_media(context["source_url"], context["license"])
        library.add_archived_media(data, person, asset_id, media, result, club, stint)
        library.save(data)
        self._sync_identity_cards(settings, person, club)
        return person, club, stint, asset_id

    def _sync_identity_cards(self, settings, person_record, organization_record=None):
        registry = IdentityCardRegistry(ROOT / settings.get("identity_cards_path", "data/identity_cards.json"))
        data = registry.load()
        person_card = registry.ensure_person(data, person_record)
        organization_card = registry.ensure_organization(data, organization_record)
        cards = TelegramIdentityCards(self.token, settings.get("identity_cards_channel_id"), self.timeout)
        if cards.enabled:
            person_message_id = cards.upsert(person_card, registry.person_text(person_card))
            if person_message_id:
                person_card["card_message_id"] = person_message_id
            if organization_card:
                organization_message_id = cards.upsert(organization_card, registry.organization_text(organization_card))
                if organization_message_id:
                    organization_card["card_message_id"] = organization_message_id
        registry.save(data)

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
            media_library_mode = bool(updates_state.get("media_library_mode", False))
            identity_cards_mode = bool(updates_state.get("identity_cards_mode", False))
            manual_media = updates_state.get("manual_media")

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
            elif command == "/medialibrary":
                self._send(chat_id, self._media_library_status())
            elif command == "/identitycards":
                self._send(chat_id, self._identity_cards_status())
            elif command == "/setmedialibrary":
                if args:
                    try:
                        channel = self._channel_from_input(args[0], " ".join(args[1:]).strip() or None)
                        name, channel_id = self._set_media_library(channel)
                        updates_state["media_library_mode"] = False
                        self._send(chat_id, f"✅ تم ربط مكتبة الصور تلقائيًا.\n\nالقناة: {name}\nالمعرّف: {channel_id}")
                    except ValueError as exc:
                        self._send(chat_id, f"❌ {exc}")
                else:
                    updates_state["media_library_mode"] = True
                    updates_state["addchannel_mode"] = False
                    updates_state["identity_cards_mode"] = False
                    self._send(
                        chat_id,
                        "🗂 أعد توجيه أي منشور من قناة مكتبة الصور الخاصة.\n"
                        "يمكنك إرسال هذا التوجيه مباشرة بعد الأمر؛ لا حاجة لانتظار رد البوت.\n"
                        "يجب أن يكون البوت مشرفًا فيها بصلاحية نشر الرسائل.",
                    )
            elif command == "/setidentitylibrary":
                if args:
                    try:
                        channel = self._channel_from_input(args[0], " ".join(args[1:]).strip() or None)
                        name, channel_id = self._set_identity_cards_library(channel)
                        updates_state["identity_cards_mode"] = False
                        self._send(chat_id, f"✅ تم ربط قناة بطاقات الهوية.\n\nالقناة: {name}\nالمعرّف: {channel_id}")
                    except ValueError as exc:
                        self._send(chat_id, f"❌ {exc}")
                else:
                    updates_state["identity_cards_mode"] = True
                    updates_state["addchannel_mode"] = False
                    updates_state["media_library_mode"] = False
                    self._send(
                        chat_id,
                        "🪪 أعد توجيه أي منشور من قناة بطاقات الهوية الخاصة.\n"
                        "يمكنك إرسال هذا التوجيه مباشرة بعد الأمر؛ لا حاجة لانتظار رد البوت.\n"
                        "يجب أن يكون البوت مشرفًا فيها بصلاحية نشر الرسائل.",
                    )
            elif command == "/addmedia":
                try:
                    updates_state["manual_media"] = self._manual_media_context(args)
                    updates_state["addchannel_mode"] = False
                    updates_state["media_library_mode"] = False
                    updates_state["identity_cards_mode"] = False
                    self._send(
                        chat_id,
                        "🖼 أرسل الصورة الآن كصورة Telegram (وليس كملف).\n"
                        "سيحفظها البوت في المكتبة مع النادي والسنة والرخصة التي أدخلتها.\n\n"
                        "للإلغاء استخدم /cancel.",
                    )
                except ValueError as exc:
                    self._send(chat_id, f"❌ {exc}")
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
                        channel = self._channel_from_input(args[0], " ".join(args[1:]).strip() or None)
                        added = self._add_channel(channel)
                        updates_state["addchannel_mode"] = False
                        status = "تمت الإضافة والتفعيل" if added else "كانت موجودة وتم تفعيلها"
                        self._send(chat_id, f"✅ {status}.\n\nالاسم: {channel['name']}\nالمعرّف: {channel['id']}")
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
                updates_state["media_library_mode"] = False
                updates_state["identity_cards_mode"] = False
                updates_state["manual_media"] = None
                self._send(chat_id, "🛑 تم إلغاء العملية الحالية.")
            elif command.startswith("/"):
                self._send(chat_id, self._help_message())
            else:
                channel = self._forwarded_channel(message)
                photos = message.get("photo") or []
                if manual_media:
                    if not photos:
                        self._send(chat_id, "ℹ️ أرسل الصورة كصورة Telegram الآن، أو استخدم /cancel.")
                    else:
                        try:
                            person, club, stint, asset_id = self._archive_manual_media(photos[-1].get("file_id"), manual_media)
                            updates_state["manual_media"] = None
                            context_label = f"{club['name']} — {stint['start_year']}" if club and stint else "صورة عامة"
                            self._send(
                                chat_id,
                                "✅ أُضيفت الصورة إلى المكتبة.\n\n"
                                f"الشخص: {person['name']} ({person['person_id']})\n"
                                f"السياق: {context_label}\n"
                                f"الأصل: {asset_id}",
                            )
                        except ValueError as exc:
                            self._send(chat_id, f"❌ {exc}")
                elif channel and media_library_mode:
                    try:
                        name, channel_id = self._set_media_library(channel)
                        updates_state["media_library_mode"] = False
                        self._send(chat_id, f"✅ تم ربط مكتبة الصور.\n\nالقناة: {name}\nالمعرّف: {channel_id}")
                    except ValueError as exc:
                        self._send(chat_id, f"❌ {exc}")
                elif channel and identity_cards_mode:
                    try:
                        name, channel_id = self._set_identity_cards_library(channel)
                        updates_state["identity_cards_mode"] = False
                        self._send(chat_id, f"✅ تم ربط قناة بطاقات الهوية.\n\nالقناة: {name}\nالمعرّف: {channel_id}")
                    except ValueError as exc:
                        self._send(chat_id, f"❌ {exc}")
                elif channel and addchannel_mode:
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
