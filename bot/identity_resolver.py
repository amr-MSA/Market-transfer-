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
_ORGANIZATION_TERMS = ("football club", "association football club", "national football team", "soccer club")


class WikidataIdentitySource:
    def __init__(self, timeout=15, user_agent="TransferConfirmationBot/5.0"):
        self.timeout = timeout
        self.headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}

    def candidates(self, name, entity_type, organization=None):
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

        organization_ids = self._organization_ids(organization) if organization else set()
        output = []
        for item in exact:
            description = str(item.get("description") or "")
            if not any(term in description.casefold() for term in _FOOTBALL_TERMS):
                continue
            facts = self._entity_facts(item.get("id"), item.get("label") or name, description, entity_type)
            if facts:
                output.append(facts)
        if organization_ids:
            contextual = [facts for facts in output if organization_ids.intersection(facts.get("organization_ids") or [])]
            # An exact organization match can safely narrow multiple identical names.
            if contextual:
                return contextual
        return output

    def facts_for_identity_key(self, identity_key, entity_type):
        prefix, separator, qid = str(identity_key or "").partition(":")
        if prefix != "wikidata" or not separator or not re.fullmatch(r"Q\d+", qid):
            return None
        return self._entity_facts(qid, qid, "manual identity selection", entity_type)

    def _organization_ids(self, name):
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
            return set()
        return {
            item["id"]
            for item in search
            if self._same_name(name, item.get("label"))
            and any(term in str(item.get("description") or "").casefold() for term in _ORGANIZATION_TERMS)
        }

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
            "organization_ids": self._claim_ids(claims, "P54"),
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

    def resolve(self, data, name, entity_type, organization=None):
        local = self.registry.find_people_by_name(data, name, entity_type)
        remote = self.source.candidates(name, entity_type, organization=organization)
        unique_by_key = {item["identity_key"]: item for item in remote if item.get("identity_key")}
        if len(unique_by_key) != 1:
            return {
                "status": "AMBIGUOUS" if unique_by_key or local else "NOT_FOUND",
                "candidates": self._combine_candidates(list(unique_by_key.values()), local),
            }

        facts = next(iter(unique_by_key.values()))
        same_key = self.registry.find_person_by_identity_key(data, facts["identity_key"])
        if same_key:
            return {"status": "EXISTING", "card": same_key, "facts": facts}
        if len(local) == 1:
            if local[0].get("identity_key"):
                return {"status": "AMBIGUOUS", "candidates": self._combine_candidates([facts], local)}
            return {"status": "VERIFY_EXISTING", "card": local[0], "facts": facts}
        if len(local) > 1:
            return {"status": "AMBIGUOUS", "candidates": self._combine_candidates([facts], local)}
        return {"status": "CREATE_VERIFIED", "facts": facts}

    @staticmethod
    def _combine_candidates(remote, local):
        combined = []
        positions = {}
        for candidate in [*(remote or []), *(local or [])]:
            key = candidate.get("identity_key") or candidate.get("person_id") or repr(candidate)
            if key not in positions:
                positions[key] = len(combined)
                combined.append(dict(candidate))
                continue
            existing = combined[positions[key]]
            for field, value in candidate.items():
                if value and not existing.get(field):
                    existing[field] = value
        return combined


def normalize_name(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"[^\w\s]", " ", value)
    return " ".join(value.casefold().split())


def ambiguity_report(name, entity_type, organization, candidates):
    """Return a readable admin report. It deliberately exposes source keys.

    The administrator needs enough source data to make an explicit selection,
    but a Telegram message must remain below the platform's message limit.
    """
    role = "لاعب" if entity_type == "player" else "مدرب"
    lines = [
        "⚠️ هوية ملتبسة — لم تُحفظ الصورة",
        f"الاسم الوارد: {name}",
        f"النوع: {role}",
        f"سياق الخبر: {organization or 'غير متوفر'}",
        "",
        f"المرشحون ({len(candidates)}):",
    ]
    for index, candidate in enumerate(candidates or [], start=1):
        aliases = ", ".join((candidate.get("aliases") or [])[:4]) or "—"
        nationality = ", ".join(candidate.get("nationality_ids") or []) or "—"
        positions = ", ".join(candidate.get("position_ids") or []) or "—"
        organizations = ", ".join(candidate.get("organization_ids") or []) or "—"
        lines.extend(
            [
                "",
                f"{index}) الاسم: {candidate.get('canonical_name') or candidate.get('name') or '—'}",
                f"   person_id المحلي: {candidate.get('person_id') or '—'}",
                f"   identity_key: {candidate.get('identity_key') or '—'}",
                f"   الميلاد: {candidate.get('birth_date') or '—'}",
                f"   الجنسية (QID): {nationality}",
                f"   المركز (QID): {positions}",
                f"   الأندية/الجهات (QID): {organizations}",
                f"   أسماء بديلة: {aliases}",
                f"   الوصف: {candidate.get('description') or '—'}",
                f"   السجل: {candidate.get('source') or 'محلي'}",
                f"   المصدر: {candidate.get('source_url') or '—'}",
            ]
        )
    lines.extend(
        [
            "",
            "للاعتماد اليدوي، أعد أمر /addmedia نفسه وأضف identity_key المختار كمعامل أخير.",
            "لن يدمج البوت أي لاعب حتى يتم الحسم صراحة.",
        ]
    )
    return "\n".join(lines)[:3900]
