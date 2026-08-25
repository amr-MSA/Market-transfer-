"""Human-readable identity cards backed by a private Telegram channel.

The JSON registry is the lookup index; Telegram is the transparent review log.
It deliberately keeps an identity_key and verification status separate from a
display name, because names are not unique player identifiers.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests
from .identity_resolver import normalize_name


class IdentityCardRegistry:
    def __init__(self, path):
        self.path = Path(path)

    @staticmethod
    def empty():
        return {"version": 2, "updated_at": None, "people": {}, "organizations": {}, "identity_index": {}, "name_index": {}}

    def load(self):
        if not self.path.exists():
            return self.empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return self.empty()
        if not isinstance(data, dict):
            return self.empty()
        data["version"] = 2
        data.setdefault("updated_at", None)
        data.setdefault("people", {})
        data.setdefault("organizations", {})
        self.rebuild_indexes(data)
        return data

    def save(self, data):
        self.rebuild_indexes(data)
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

    def ensure_person(self, data, person_record):
        person_id = person_record["person_id"]
        card = data.setdefault("people", {}).setdefault(
            person_id,
            {
                "person_id": person_id,
                "canonical_name": person_record["name"],
                "aliases": list(person_record.get("aliases") or []),
                "entity_type": person_record.get("entity_type"),
                "identity_key": None,
                "birth_date": None,
                "nationality_ids": [],
                "position_ids": [],
                "identity_source_url": None,
                "identity_verified_at": None,
                "identity_status": "PENDING_VERIFICATION",
                "card_message_id": None,
                "created_at": self._now(),
            },
        )
        card["canonical_name"] = person_record["name"]
        card["entity_type"] = person_record.get("entity_type")
        data["updated_at"] = self._now()
        return card

    def find_person_by_identity_key(self, data, identity_key):
        person_id = (data.get("identity_index") or {}).get(identity_key)
        return (data.get("people") or {}).get(person_id) if person_id else None

    def find_people_by_name(self, data, name, entity_type=None):
        candidate_ids = (data.get("name_index") or {}).get(normalize_name(name), [])
        cards = [(data.get("people") or {}).get(person_id) for person_id in candidate_ids]
        cards = [card for card in cards if card]
        return [card for card in cards if not entity_type or card.get("entity_type") == entity_type]

    def apply_facts(self, data, card, facts):
        existing_key = card.get("identity_key")
        incoming_key = facts.get("identity_key")
        if existing_key and incoming_key and existing_key != incoming_key:
            raise ValueError("identity key conflict")
        card["identity_key"] = incoming_key or existing_key
        card["canonical_name"] = facts.get("canonical_name") or card.get("canonical_name")
        aliases = [card.get("canonical_name"), *(card.get("aliases") or []), *(facts.get("aliases") or [])]
        card["aliases"] = list(dict.fromkeys(alias for alias in aliases if alias))
        card["birth_date"] = facts.get("birth_date") or card.get("birth_date")
        card["nationality_ids"] = facts.get("nationality_ids") or card.get("nationality_ids") or []
        card["position_ids"] = facts.get("position_ids") or card.get("position_ids") or []
        card["identity_source_url"] = facts.get("source_url") or card.get("identity_source_url")
        card["identity_verified_at"] = facts.get("verified_at") or card.get("identity_verified_at")
        card["identity_status"] = "VERIFIED" if card.get("identity_key") else "PENDING_VERIFICATION"
        data["updated_at"] = self._now()
        return card

    @staticmethod
    def rebuild_indexes(data):
        identity_index = {}
        name_index = {}
        for person_id, card in (data.get("people") or {}).items():
            identity_key = card.get("identity_key")
            if identity_key and identity_key not in identity_index:
                identity_index[identity_key] = person_id
            for alias in [card.get("canonical_name"), *(card.get("aliases") or [])]:
                normalized = normalize_name(alias)
                if normalized:
                    name_index.setdefault(normalized, []).append(person_id)
        data["identity_index"] = identity_index
        data["name_index"] = {key: list(dict.fromkeys(values)) for key, values in name_index.items()}

    def ensure_organization(self, data, organization_record):
        if not organization_record:
            return None
        organization_id = organization_record["club_id"]
        card = data.setdefault("organizations", {}).setdefault(
            organization_id,
            {
                "organization_id": organization_id,
                "canonical_name": organization_record["name"],
                "aliases": list(organization_record.get("aliases") or []),
                "organization_type": "organization",
                "identity_key": None,
                "country": None,
                "identity_status": "PENDING_VERIFICATION",
                "card_message_id": None,
                "created_at": self._now(),
            },
        )
        card["canonical_name"] = organization_record["name"]
        data["updated_at"] = self._now()
        return card

    @staticmethod
    def person_text(card):
        return "\n".join(
            [
                "IDENTITY_CARD",
                "entity=person",
                f"person_id={card['person_id']}",
                f"name={card['canonical_name']}",
                f"role={card.get('entity_type') or 'unknown'}",
                f"identity_key={card.get('identity_key') or 'PENDING'}",
                f"birth_date={card.get('birth_date') or 'PENDING'}",
                f"nationality_ids={','.join(card.get('nationality_ids') or []) or 'PENDING'}",
                f"position_ids={','.join(card.get('position_ids') or []) or 'PENDING'}",
                f"status={card.get('identity_status') or 'PENDING_VERIFICATION'}",
            ]
        )

    @staticmethod
    def organization_text(card):
        return "\n".join(
            [
                "IDENTITY_CARD",
                "entity=organization",
                f"organization_id={card['organization_id']}",
                f"name={card['canonical_name']}",
                f"type={card.get('organization_type') or 'organization'}",
                f"identity_key={card.get('identity_key') or 'PENDING'}",
                f"country={card.get('country') or 'PENDING'}",
                f"status={card.get('identity_status') or 'PENDING_VERIFICATION'}",
            ]
        )

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()


class TelegramIdentityCards:
    def __init__(self, token, chat_id, timeout=20):
        self.chat_id = str(chat_id) if chat_id else None
        self.timeout = timeout
        self.endpoint = f"https://api.telegram.org/bot{token}"

    @property
    def enabled(self):
        return bool(self.chat_id)

    def upsert(self, card, text):
        if not self.enabled:
            return None
        try:
            message_id = card.get("card_message_id")
            if message_id:
                response = requests.post(
                    f"{self.endpoint}/editMessageText",
                    json={"chat_id": self.chat_id, "message_id": message_id, "text": text},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                result = response.json()
                if result.get("ok"):
                    return int(message_id)

            response = requests.post(
                f"{self.endpoint}/sendMessage",
                json={"chat_id": self.chat_id, "text": text},
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()
            message = result.get("result") or {}
            return message.get("message_id") if result.get("ok") else None
        except (ValueError, requests.RequestException):
            return None
