"""Private Telegram-backed archive for approved football person images.

Telegram keeps the media file; this module keeps the durable, searchable
metadata needed to match a player/manager and reuse its `file_id` safely.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import requests


_ARCHIVABLE_SOURCES = {"wikimedia"}
_PERSON_TYPES = {"player", "manager"}


class MediaLibrary:
    """Persistent index for private Telegram media-library messages."""

    def __init__(self, path):
        self.path = Path(path)

    @staticmethod
    def empty():
        return {
            "version": 1,
            "updated_at": None,
            "next_person_number": 1,
            "next_asset_number": 1,
            "people": {},
            "assets": {},
        }

    def load(self):
        if not self.path.exists():
            return self.empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return self.empty()
        if not isinstance(data, dict) or not isinstance(data.get("people"), dict) or not isinstance(data.get("assets"), dict):
            return self.empty()
        data.setdefault("version", 1)
        data.setdefault("updated_at", None)
        data.setdefault("next_person_number", 1)
        data.setdefault("next_asset_number", 1)
        return data

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def find_media(self, data, person, entity_type):
        """Return the best approved library image for one unambiguous person."""
        normalized = self._normalize(person)
        if not normalized or entity_type not in _PERSON_TYPES:
            return None
        matches = []
        for record in data.get("people", {}).values():
            aliases = [record.get("name"), *(record.get("aliases") or [])]
            if record.get("entity_type") == entity_type and normalized in {self._normalize(alias) for alias in aliases}:
                matches.append(record)
        if len(matches) != 1:
            return None

        person_record = matches[0]
        candidates = []
        for asset_id in person_record.get("asset_ids", []):
            asset = data.get("assets", {}).get(asset_id)
            if asset and asset.get("status") == "APPROVED" and asset.get("telegram_file_id"):
                candidates.append(asset)
        if not candidates:
            return None
        best = max(candidates, key=lambda asset: (int(asset.get("quality_score", 0)), asset.get("added_at") or ""))
        return self._as_media(best)

    def reserve_ids(self, data, person, entity_type):
        """Get an existing person id or reserve stable ids for a new asset."""
        normalized = self._normalize(person)
        for record in data.get("people", {}).values():
            aliases = [record.get("name"), *(record.get("aliases") or [])]
            if record.get("entity_type") == entity_type and normalized in {self._normalize(alias) for alias in aliases}:
                asset_id = self._next_asset_id(data)
                return record, asset_id

        person_id = f"P{int(data.get('next_person_number', 1)):07d}"
        data["next_person_number"] = int(data.get("next_person_number", 1)) + 1
        person_record = {
            "person_id": person_id,
            "name": str(person).strip(),
            "aliases": [],
            "entity_type": entity_type,
            "asset_ids": [],
            "created_at": self._now(),
        }
        data.setdefault("people", {})[person_id] = person_record
        return person_record, self._next_asset_id(data)

    def add_archived_media(self, data, person_record, asset_id, media, archive):
        """Save one successfully archived Telegram photo and its provenance."""
        asset = {
            "asset_id": asset_id,
            "person_id": person_record["person_id"],
            "telegram_file_id": archive["file_id"],
            "telegram_file_unique_id": archive.get("file_unique_id"),
            "telegram_message_id": archive.get("message_id"),
            "source": media.get("source"),
            "source_url": media.get("credit_url") or media.get("url"),
            "credit_name": media.get("credit_name"),
            "credit_license": media.get("credit_license"),
            "width": archive.get("width"),
            "height": archive.get("height"),
            "quality_score": self._quality_score(archive),
            "status": "APPROVED",
            "added_at": self._now(),
        }
        data.setdefault("assets", {})[asset_id] = asset
        person_record.setdefault("asset_ids", []).append(asset_id)
        data["updated_at"] = self._now()
        return self._as_media(asset)

    @staticmethod
    def is_archivable(media):
        return (
            isinstance(media, dict)
            and media.get("source") in _ARCHIVABLE_SOURCES
            and bool(media.get("credit_license"))
            and bool(media.get("url"))
        )

    def _next_asset_id(self, data):
        asset_id = f"IMG{int(data.get('next_asset_number', 1)):07d}"
        data["next_asset_number"] = int(data.get("next_asset_number", 1)) + 1
        return asset_id

    @staticmethod
    def _as_media(asset):
        return {
            "url": asset["telegram_file_id"],
            "source": asset.get("source"),
            "credit_name": asset.get("credit_name"),
            "credit_license": asset.get("credit_license"),
            "credit_url": asset.get("source_url"),
            "library_asset_id": asset.get("asset_id"),
            "library_person_id": asset.get("person_id"),
        }

    @staticmethod
    def _quality_score(archive):
        width = int(archive.get("width") or 0)
        height = int(archive.get("height") or 0)
        short_edge = min(width, height) if width and height else 0
        return min(100, max(1, round((short_edge / 960) * 100)))

    @staticmethod
    def _normalize(value):
        value = unicodedata.normalize("NFKD", str(value or ""))
        value = "".join(char for char in value if not unicodedata.combining(char))
        value = re.sub(r"[^\w\s]", " ", value)
        return " ".join(value.casefold().split())

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()


class TelegramMediaArchive:
    """Uploads an approved external image once and returns Telegram file ids."""

    def __init__(self, token, chat_id, timeout=20):
        self.chat_id = str(chat_id) if chat_id else None
        self.timeout = timeout
        self.endpoint = f"https://api.telegram.org/bot{token}/sendPhoto"

    @property
    def enabled(self):
        return bool(self.chat_id)

    def archive(self, media, person_record, asset_id):
        if not self.enabled or not MediaLibrary.is_archivable(media):
            return None
        caption = (
            f"LIBRARY_ASSET\n"
            f"person_id={person_record['person_id']}\n"
            f"asset_id={asset_id}\n"
            f"name={person_record['name']}\n"
            f"source={media.get('source')}\n"
            f"license={media.get('credit_license')}"
        )
        try:
            response = requests.post(
                self.endpoint,
                json={"chat_id": self.chat_id, "photo": media["url"], "caption": caption},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                return None
            message = payload.get("result") or {}
            photos = message.get("photo") or []
            if not photos:
                return None
            photo = photos[-1]
            return {
                "file_id": photo.get("file_id"),
                "file_unique_id": photo.get("file_unique_id"),
                "message_id": message.get("message_id"),
                "width": photo.get("width"),
                "height": photo.get("height"),
            }
        except (ValueError, requests.RequestException):
            return None
