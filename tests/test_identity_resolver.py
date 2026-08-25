from bot.identity_cards import IdentityCardRegistry
from bot.identity_resolver import IdentityResolver


class Source:
    def __init__(self, candidates):
        self._candidates = candidates
        self.calls = 0

    def candidates(self, name, entity_type, organization=None):
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


def test_verified_identity_key_still_requires_matching_external_confirmation(tmp_path):
    registry = IdentityCardRegistry(tmp_path / "identity.json")
    data = registry.load()
    card = registry.ensure_person(data, _person("P0000001"))
    registry.apply_facts(data, card, _facts())
    registry.rebuild_indexes(data)
    source = Source([_facts()])

    decision = IdentityResolver(registry, source).resolve(data, "Mohamed Ali", "player")

    assert decision["status"] == "EXISTING"
    assert decision["card"]["person_id"] == "P0000001"
    assert source.calls == 1


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


def test_one_local_verified_name_does_not_bypass_multiple_external_candidates(tmp_path):
    registry = IdentityCardRegistry(tmp_path / "identity.json")
    data = registry.load()
    local = registry.ensure_person(data, _person("P0000001", "Alex Silva"))
    registry.apply_facts(data, local, _facts("wikidata:Q1", "Alex Silva"))
    registry.rebuild_indexes(data)

    decision = IdentityResolver(
        registry,
        Source([_facts("wikidata:Q1", "Alex Silva"), _facts("wikidata:Q2", "Alex Silva")]),
    ).resolve(data, "Alex Silva", "player", organization="Arsenal")

    assert decision["status"] == "AMBIGUOUS"
    assert {candidate["identity_key"] for candidate in decision["candidates"]} == {"wikidata:Q1", "wikidata:Q2"}
    assert any(candidate.get("person_id") == "P0000001" for candidate in decision["candidates"])
