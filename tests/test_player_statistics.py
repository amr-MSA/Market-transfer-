from datetime import datetime, timezone

from bot.player_statistics import ApiFootballPlayerStatistics


def test_previous_completed_season_uses_last_full_european_season(tmp_path):
    stats = ApiFootballPlayerStatistics(
        "KEY", tmp_path / "stats.json", now_fn=lambda: datetime(2026, 8, 26, tzinfo=timezone.utc)
    )
    assert stats.previous_completed_season_start() == 2025


def test_snapshot_aggregates_only_the_same_season_and_keeps_competition_rows(tmp_path):
    stats = ApiFootballPlayerStatistics(
        "KEY", tmp_path / "stats.json", now_fn=lambda: datetime(2026, 8, 26, tzinfo=timezone.utc)
    )
    rows = [
        {
            "league": {"name": "Ligue 1", "season": 2025},
            "games": {"appearences": 20, "minutes": 1400, "position": "Midfielder"},
            "goals": {"total": 4, "assists": 6, "conceded": None, "saves": None},
            "passes": {"key": 35}, "tackles": {"total": 20, "interceptions": 12, "blocks": 5},
        },
        {
            "league": {"name": "Coupe de France", "season": 2025},
            "games": {"appearences": 4, "minutes": 300, "position": "Midfielder"},
            "goals": {"total": 1, "assists": 1, "conceded": None, "saves": None},
            "passes": {"key": 8}, "tackles": {"total": 5, "interceptions": 3, "blocks": 1},
        },
    ]
    snapshot = stats._build_snapshot(rows, 2025)
    assert snapshot["metrics"]["appearances"] == 24
    assert snapshot["metrics"]["goals"] == 5
    assert snapshot["metrics"]["key_passes"] == 43
    assert [row["name_ar"] for row in snapshot["competitions"]] == ["الدوري الفرنسي", "كأس فرنسا"]


def test_refresh_card_matches_the_previous_club_and_reuses_cached_snapshot(tmp_path, monkeypatch):
    stats = ApiFootballPlayerStatistics(
        "KEY", tmp_path / "stats.json", now_fn=lambda: datetime(2026, 8, 26, tzinfo=timezone.utc)
    )
    calls = []

    def fake_get(path, params):
        calls.append((path, params))
        if path == "teams":
            return [{"team": {"id": 79, "name": "Lille"}}]
        return [{
            "player": {"id": 12, "name": "Ayyoub Bouaddi"},
            "statistics": [{
                "league": {"name": "Ligue 1", "season": 2025},
                "games": {"appearences": 20, "minutes": 1400, "position": "Midfielder"},
                "goals": {"total": 4, "assists": 6, "conceded": None, "saves": None},
                "passes": {"key": 35}, "tackles": {"total": 20, "interceptions": 12, "blocks": 5},
            }],
        }]

    monkeypatch.setattr(stats, "_get", fake_get)
    card = {"identity_key": "wikidata:Q1", "canonical_name_original": "Ayyoub Bouaddi"}

    assert stats.refresh_card(card, "Lille") is True
    assert card["season_stats"]["metrics"]["goals"] == 4
    assert stats.refresh_card(card, "Lille") is False
    assert len(calls) == 2
