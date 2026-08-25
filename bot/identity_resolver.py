"""Identity decisions for football people.

Names are discovery hints only. A person becomes reusable only after a stable
reference key has been saved, or after a human explicitly reviews an
ambiguous candidate. The resolver never silently merges multiple matches.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

import requests


WIKIDATA_API = "https://www.wikidata.org/w/api.php"
_FOOTBALL_TERMS = ("football", "soccer", "association football")


class WikidataIdentitySource:
    def __init__(self, timeout=15, user_agent="TransferConfirmationBot/5.0"):
        self.timeout = timeout
        self.headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}

    def candidates(self, name, entity_type):
        try:
            response = requests.get(
                WIKIDATA_API,
                params={
                    "action": "wbsearchentities",
                    "search": name,
                    "language": "en",
                    "type": "item",
                    "limit": 8,
                    "format": "json",
                    "maxlag": 5,
                },
                headers=self.headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            search = response.json().get("search") or []
        except (ValueError, requests.RequestException):
            return []

        exact = [item for item in search if self._same_name(name, item.get("label")) or any(self._same_name(name, alias) for alias in item.get("aliases") or [])]
        if not exact:
            return []

        output = []
        for item in exact:
            description = str(item.get("description") or "")
            if not any(term in description.casefold() for term in _FOOTBALL_TERMS):
                continue
            facts = self._entity_facts(item.get("id"), item.get("label") or name, description, entity_type)
            if facts:
                output.append(facts)
        return output

    def _entity_facts(self, qid, fallback_name, description, entity_type):
        if not qid:
            return None
        try:
            response = requests.get(
                WIKIDATA_API,
                params={
                    "action": "wbgetentities",
                    "ids": qid,
                    "props": "labels|aliases|claims",
                    "languages": "en|ar",
                    "format": "json",
                    "maxlag": 5,
                },
                headers=self.headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            entity = (response.json().get("entities") or {}).get(qid) or {}
        except (ValueError, requests.RequestException):
            return None

        claims = entity.get("claims") or {}
        name = self._label(entity, "en") or self._label(entity, "ar") or fallback_name
        aliases = self._aliases(entity)
        return {
            "identity_key": f"wikidata:{qid}",
            "canonical_name": name,
            "aliases": aliases,
            "birth_date": self._claim_time(claims, "P569"),
            "nationality_ids": self._claim_ids(claims, "P27"),
            "position_ids": self._claim_ids(claims, "P413"),
            "source_url": f"https://www.wikidata.org/wiki/{qid}",
            "source": "wikidata",
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "entity_type": entity_type,
            "description": description,
        }

    @staticmethod
    def _claim_time(claims, property_id):
        for claim in claims.get(property_id) or []:
            value = (((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {})
            raw = str(value.get("time") or "")
            match = re.fullmatch(r"[+-](\d{4,})-\d\d-\d\dT.*", raw)
            if match:
                return raw[1:11]
        return None

    @staticmethod
    def _claim_ids(claims, property_id):
        values = []
        for claim in claims.get(property_id) or []:
            value = (((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {})
            qid = value.get("id")
            if qid and qid not in values:
                values.append(qid)
        return values

    @staticmethod
    def _label(entity, language):
        return ((entity.get("labels") or {}).get(language) or {}).get("value")

    @staticmethod
    def _aliases(entity):
        aliases = []
        for language_aliases in (entity.get("aliases") or {}).values():
            for alias in language_aliases or []:
                value = alias.get("value")
                if value and value not in aliases:
                    aliases.append(value)
        return aliases

    @staticmethod
    def _same_name(left, right):
        return normalize_name(left) == normalize_name(right)


class IdentityResolver:
    """Makes safe local/external identity decisions without name-only merges."""

    def __init__(self, registry, source=None):
        self.registry = registry
        self.source = source or WikidataIdentitySource()

    def resolve(self, data, name, entity_type):
        local = self.registry.find_people_by_name(data, name, entity_type)
        verified = [card for card in local if card.get("identity_key") and card.get("identity_status") == "VERIFIED"]
        if len(verified) == 1:
            return {"status": "EXISTING", "card": verified[0], "facts": None}
        if len(verified) > 1:
            return {"status": "AMBIGUOUS", "candidates": verified}

        remote = self.source.candidates(name, entity_type)
        unique_by_key = {item["identity_key"]: item for item in remote if item.get("identity_key")}
        if len(unique_by_key) != 1:
            return {"status": "AMBIGUOUS" if unique_by_key else "NOT_FOUND", "candidates": list(unique_by_key.values())}

        facts = next(iter(unique_by_key.values()))
        same_key = self.registry.find_person_by_identity_key(data, facts["identity_key"])
        if same_key:
            return {"status": "EXISTING", "card": same_key, "facts": facts}
        if len(local) == 1:
            return {"status": "VERIFY_EXISTING", "card": local[0], "facts": facts}
        if len(local) > 1:
            return {"status": "AMBIGUOUS", "candidates": local}
        return {"status": "CREATE_VERIFIED", "facts": facts}


def normalize_name(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"[^\w\s]", " ", value)
    return " ".join(value.casefold().split())
