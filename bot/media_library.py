"""Telegram-backed, context-aware archive for approved football images.

Telegram stores the binary media; this module owns the durable index that
matches a person, club stint, and approved image without confusing old kits.
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
    """Persistent index for private Telegram media-library messages.

    Person IDs never change. Club-and-year keys describe visual context, so a
    player can have a distinct approved image for every club stint.
    """

    def __init__(self, path):
        self.path = Path(path)

    @staticmethod
    def empty():
        return {
            "version": 2,
            "updated_at": None,
            "next_person_number": 1,
            "next_club_number": 1,
            "people": {},
            "clubs": {},
            "stints": {},
            "assets": {},
        }

    def load(self):
        if not self.path.exists():
            return self.empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return self.empty()
        return self._upgrade(data)

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

    def find_media(self, data, person, entity_type, club=None, year=None, person_id=None, require_modesty_approved=False):
        """Return the best approved image for a person in the requested club.

        A generic approved portrait may serve as a fallback. An image tied to
        another club is deliberately never used when a club was requested.
        """
        person_record = data.get("people", {}).get(person_id) if person_id else self._find_person(data, person, entity_type)
        if person_record and person_record.get("entity_type") != entity_type:
            return None
        if not person_record:
            return None

        club_requested = bool(self._normalize(club))
        target_club = self._find_club(data, club) if club_requested else None
        target_year = self._coerce_year(year)
        candidates = []
        for asset_id in person_record.get("asset_ids", []):
            asset = data.get("assets", {}).get(asset_id)
            if not asset or asset.get("status") != "APPROVED" or not asset.get("telegram_file_id"):
                continue
            if require_modesty_approved and not asset.get("modesty_approved"):
                continue

            asset_club_id = asset.get("club_id")
            if club_requested:
                if target_club and asset_club_id == target_club["club_id"]:
                    context_rank = 2
                elif not asset_club_id:
                    context_rank = 1
                else:
                    continue
            else:
                context_rank = 1 if not asset_club_id else 0

            year_rank = int(bool(target_year and asset.get("start_year") == target_year))
            candidates.append((context_rank, year_rank, int(asset.get("quality_score", 0)), asset.get("added_at") or "", asset))

        if not candidates:
            return None
        return self._as_media(max(candidates, key=lambda item: item[:-1])[-1])

    def reserve_contextual_ids(self, data, person, entity_type, club=None, start_year=None, person_id=None):
        """Reserve stable person, club/stint, and context-specific image IDs."""
        if entity_type not in _PERSON_TYPES:
            raise ValueError("entity_type must be player or manager")
        person_name = str(person or "").strip()
        if not person_name:
            raise ValueError("person name is required")

        person_record = data.get("people", {}).get(person_id) if person_id else self._find_person(data, person_name, entity_type)
        if person_record and person_record.get("entity_type") != entity_type:
            raise ValueError("person_id belongs to a different entity type")
        if not person_record:
            resolved_person_id = person_id or f"P{int(data.get('next_person_number', 1)):07d}"
            numeric_id = int(str(resolved_person_id).removeprefix("P") or 0)
            data["next_person_number"] = max(int(data.get("next_person_number", 1)), numeric_id + 1)
            person_record = {
                "person_id": resolved_person_id,
                "name": person_name,
                "aliases": [],
                "entity_type": entity_type,
                "asset_ids": [],
                "stint_ids": [],
                "created_at": self._now(),
            }
            data.setdefault("people", {})[resolved_person_id] = person_record

        club_record = None
        stint_record = None
        year = self._coerce_year(start_year)
        if club:
            if not year:
                raise ValueError("club-specific images require a four-digit start year")
            club_record = self._find_club(data, club)
            if not club_record:
                club_id = f"C{int(data.get('next_club_number', 1)):04d}"
                data["next_club_number"] = int(data.get("next_club_number", 1)) + 1
                club_record = {
                    "club_id": club_id,
                    "name": str(club).strip(),
                    "aliases": [],
                    "created_at": self._now(),
                }
                data.setdefault("clubs", {})[club_id] = club_record

            club_code = club_record["club_id"][1:]
            person_code = person_record["person_id"][1:]
            stint_id = f"ST-{club_code}-{year}-{person_code}"
            stint_record = data.setdefault("stints", {}).get(stint_id)
            if not stint_record:
                stint_record = {
                    "stint_id": stint_id,
                    "person_id": person_record["person_id"],
                    "club_id": club_record["club_id"],
                    "start_year": year,
                    "asset_ids": [],
                    "visual_key": f"{club_code}-{year}-{person_code}",
                    "created_at": self._now(),
                }
                data["stints"][stint_id] = stint_record
                person_record.setdefault("stint_ids", []).append(stint_id)

        context_assets = (stint_record or person_record).get("asset_ids", [])
        sequence = len(context_assets) + 1
        person_code = person_record["person_id"][1:]
        if stint_record:
            club_code = club_record["club_id"][1:]
            asset_id = f"IMG-{club_code}-{year}-{person_code}-{sequence:02d}"
        else:
            asset_id = f"IMG-GEN-{person_code}-{sequence:02d}"
        return person_record, club_record, stint_record, asset_id

    def reserve_ids(self, data, person, entity_type, person_id=None):
        """Compatibility wrapper for generic portraits used by auto-import."""
        person_record, _, _, asset_id = self.reserve_contextual_ids(data, person, entity_type, person_id=person_id)
        return person_record, asset_id

    def add_archived_media(self, data, person_record, asset_id, media, archive, club_record=None, stint_record=None):
        """Save one successfully archived Telegram photo and its provenance."""
        asset = {
            "asset_id": asset_id,
            "person_id": person_record["person_id"],
            "club_id": club_record.get("club_id") if club_record else None,
            "stint_id": stint_record.get("stint_id") if stint_record else None,
            "start_year": stint_record.get("start_year") if stint_record else None,
            "context_type": "club_stint" if stint_record else "generic",
            "visual_key": stint_record.get("visual_key") if stint_record else f"GEN-{person_record['person_id'][1:]}",
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
            "modesty_approved": bool(media.get("modesty_approved")),
            "added_at": self._now(),
        }
        data.setdefault("assets", {})[asset_id] = asset
        person_record.setdefault("asset_ids", []).append(asset_id)
        if stint_record:
            stint_record.setdefault("asset_ids", []).append(asset_id)
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

    @staticmethod
    def manual_media(source_url, license_name, credit_name="Administrator confirmed"):
        return {
            "source": "manual",
            "url": source_url,
            "credit_url": source_url,
            "credit_name": credit_name,
            "credit_license": license_name,
            "modesty_approved": True,
        }

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
            "library_club_id": asset.get("club_id"),
            "library_stint_id": asset.get("stint_id"),
        }

    def _upgrade(self, data):
        if not isinstance(data, dict) or not isinstance(data.get("people"), dict) or not isinstance(data.get("assets"), dict):
            return self.empty()
        data["version"] = 2
        data.setdefault("updated_at", None)
        data.setdefault("next_person_number", 1)
        data.setdefault("next_club_number", 1)
        data.setdefault("clubs", {})
        data.setdefault("stints", {})
        for person in data["people"].values():
            person.setdefault("asset_ids", [])
            person.setdefault("stint_ids", [])
            person.setdefault("aliases", [])
        for asset in data["assets"].values():
            asset.setdefault("club_id", None)
            asset.setdefault("stint_id", None)
            asset.setdefault("start_year", None)
            asset.setdefault("context_type", "generic")
            asset.setdefault("visual_key", f"GEN-{str(asset.get('person_id') or '')[1:]}")
        return data

    def _find_person(self, data, person, entity_type):
        normalized = self._normalize(person)
        if not normalized or entity_type not in _PERSON_TYPES:
            return None
        matches = []
        for record in data.get("people", {}).values():
            aliases = [record.get("name"), *(record.get("aliases") or [])]
            if record.get("entity_type") == entity_type and normalized in {self._normalize(alias) for alias in aliases}:
                matches.append(record)
        return matches[0] if len(matches) == 1 else None

    def _find_club(self, data, club):
        normalized = self._normalize(club)
        if not normalized:
            return None
        matches = []
        for record in data.get("clubs", {}).values():
            aliases = [record.get("name"), *(record.get("aliases") or [])]
            if normalized in {self._normalize(alias) for alias in aliases}:
                matches.append(record)
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _coerce_year(value):
        try:
            year = int(value)
        except (TypeError, ValueError):
            return None
        return year if 1850 <= year <= 2200 else None

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
    """Uploads approved images once and returns reusable Telegram file IDs."""

    def __init__(self, token, chat_id, timeout=20):
        self.chat_id = str(chat_id) if chat_id else None
        self.timeout = timeout
        self.endpoint = f"https://api.telegram.org/bot{token}/sendPhoto"

    @property
    def enabled(self):
        return bool(self.chat_id)

    def archive(self, media, person_record, asset_id, club_record=None, stint_record=None):
        if not self.enabled or not MediaLibrary.is_archivable(media):
            return None
        return self._send_photo(
            media["url"],
            self._caption(person_record, asset_id, media.get("source"), media.get("credit_license"), club_record, stint_record),
        )

    def archive_manual(self, file_id, person_record, asset_id, license_name, club_record, stint_record):
        if not self.enabled or not file_id or not license_name:
            return None
        return self._send_photo(
            file_id,
            self._caption(person_record, asset_id, "manual", license_name, club_record, stint_record),
        )

    def _send_photo(self, photo, caption):
        try:
            response = requests.post(
                self.endpoint,
                json={"chat_id": self.chat_id, "photo": photo, "caption": caption},
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
            photo_data = photos[-1]
            return {
                "file_id": photo_data.get("file_id"),
                "file_unique_id": photo_data.get("file_unique_id"),
                "message_id": message.get("message_id"),
                "width": photo_data.get("width"),
                "height": photo_data.get("height"),
            }
        except (ValueError, requests.RequestException):
            return None

    @staticmethod
    def _caption(person_record, asset_id, source, license_name, club_record=None, stint_record=None):
        lines = [
            "LIBRARY_ASSET",
            f"person_id={person_record['person_id']}",
            f"asset_id={asset_id}",
            f"name={person_record['name']}",
            f"source={source}",
            f"license={license_name}",
        ]
        if club_record and stint_record:
            lines.extend([
                "context=club_stint",
                f"club_id={club_record['club_id']}",
                f"club={club_record['name']}",
                f"start_year={stint_record['start_year']}",
                f"visual_key={stint_record['visual_key']}",
            ])
        else:
            lines.append("context=generic")
        return "\n".join(lines)
