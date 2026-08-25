from bot.identity_cards import IdentityCardRegistry
from bot.identity_resolver import IdentityResolver


class Source:
    def __init__(self, candidates):
        self._candidates = candidates
        self.calls = 0

    def candidates(self, name, entity_type):
        self.calls += 1
        return self._candidates


def _person(person_id, name="Mohamed Ali"):
    return {"person_id": person_id, "name": name, "aliases": [], "entity_type": "player"}


def _facts(key="wikidata:Q42", name="Mohamed Ali"):
    return {
        "identity_key": key,
        "canonical_name": name,
        "aliases": [name],
        "birth_date": "2002-05-14",
        "nationality_ids": ["Q79"],
        "position_ids": ["Q193592"],
        "source_url": "https://www.wikidata.org/wiki/Q42",
        "verified_at": "2026-08-25T00:00:00+00:00",
    }


def test_verified_identity_key_wins_without_external_lookup(tmp_path):
    registry = IdentityCardRegistry(tmp_path / "identity.json")
    data = registry.load()
    card = registry.ensure_person(data, _person("P0000001"))
    registry.apply_facts(data, card, _facts())
    registry.rebuild_indexes(data)
    source = Source([])

    decision = IdentityResolver(registry, source).resolve(data, "Mohamed Ali", "player")

    assert decision["status"] == "EXISTING"
    assert decision["card"]["person_id"] == "P0000001"
    assert source.calls == 0


def test_same_name_multiple_verified_people_is_ambiguous(tmp_path):
    registry = IdentityCardRegistry(tmp_path / "identity.json")
    data = registry.load()
    one = registry.ensure_person(data, _person("P0000001"))
    two = registry.ensure_person(data, _person("P0000002"))
    registry.apply_facts(data, one, _facts("wikidata:Q1"))
    registry.apply_facts(data, two, _facts("wikidata:Q2"))
    registry.rebuild_indexes(data)

    decision = IdentityResolver(registry, Source([])).resolve(data, "Mohamed Ali", "player")

    assert decision["status"] == "AMBIGUOUS"
    assert {card["person_id"] for card in decision["candidates"]} == {"P0000001", "P0000002"}


def test_unique_trusted_candidate_creates_verified_identity_decision(tmp_path):
    registry = IdentityCardRegistry(tmp_path / "identity.json")
    data = registry.load()
    facts = _facts("wikidata:Q99", "Ezri Konsa")

    decision = IdentityResolver(registry, Source([facts])).resolve(data, "Ezri Konsa", "player")

    assert decision["status"] == "CREATE_VERIFIED"
    assert decision["facts"]["identity_key"] == "wikidata:Q99"
