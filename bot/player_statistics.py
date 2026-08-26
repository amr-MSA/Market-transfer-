"""Optional, cached player season statistics from API-Football.

This module never runs without ``API_FOOTBALL_KEY``. It uses the previous
completed season, keeps one club and one season per snapshot, and returns no
numbers when a player/team match cannot be made safely.
"""

from __future__ import annotations

import json
import re
import tempfile
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests


API_BASE_URL = "https://v3.football.api-sports.io"
API_DOCS_URL = "https://www.api-football.com/documentation-v3"

_COMPETITION_AR = {
    "Premier League": "الدوري الإنجليزي",
    "La Liga": "الدوري الإسباني",
    "Ligue 1": "الدوري الفرنسي",
    "Serie A": "الدوري الإيطالي",
    "Bundesliga": "الدوري الألماني",
    "UEFA Champions League": "دوري أبطال أوروبا",
    "UEFA Europa League": "الدوري الأوروبي",
    "UEFA Europa Conference League": "دوري المؤتمر الأوروبي",
    "Coupe de France": "كأس فرنسا",
    "FA Cup": "كأس إنجلترا",
    "EFL Cup": "كأس الرابطة الإنجليزية",
    "Copa del Rey": "كأس ملك إسبانيا",
    "Coppa Italia": "كأس إيطاليا",
    "DFB Pokal": "كأس ألمانيا",
}


class ApiFootballPlayerStatistics:
    def __init__(self, api_key, cache_path, timeout=20, cache_days=30, now_fn=None):
        self.api_key = (api_key or "").strip()
        self.cache_path = Path(cache_path)
        self.timeout = timeout
        self.cache_days = max(1, int(cache_days))
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.cache = self._load_cache()

    @property
    def enabled(self):
        return bool(self.api_key)

    def refresh_card(self, card, previous_club):
        """Refresh a verified card only when the cached previous season is stale."""
        identity_key = card.get("identity_key")
        player_name = card.get("canonical_name_original") or card.get("canonical_name")
        if not self.enabled or not identity_key or not player_name or not previous_club:
            return False
        season_start = self.previous_completed_season_start()
        cache_key = f"{identity_key}|{self._norm(previous_club)}|{season_start}"
        cached = (self.cache.get("entries") or {}).get(cache_key)
        snapshot = cached.get("snapshot") if self._fresh(cached) else None
        if snapshot is None:
            snapshot = self._fetch_snapshot(player_name, previous_club, season_start)
            if snapshot is None:
                return False
            self.cache.setdefault("entries", {})[cache_key] = {
                "fetched_at": self.now_fn().isoformat(),
                "snapshot": snapshot,
            }
            self._save_cache()
        if card.get("season_stats") == snapshot:
            return False
        card["season_stats"] = snapshot
        return True

    def previous_completed_season_start(self):
        now = self.now_fn()
        # European seasons normally start in the second half of the year.
        return now.year - 1 if now.month >= 7 else now.year - 2

    def _fetch_snapshot(self, player_name, club_name, season_start):
        team = self._unique_team(club_name)
        if not team:
            return None
        response = self._get("players", {"team": team["id"], "search": player_name, "season": season_start})
        candidates = response if isinstance(response, list) else []
        exact = [item for item in candidates if self._same_name((item.get("player") or {}).get("name"), player_name)]
        if len(exact) != 1:
            return None
        statistics = exact[0].get("statistics") or []
        rows = [row for row in statistics if isinstance(row, dict) and (row.get("league") or {}).get("season") == season_start]
        if not rows:
            return None
        return self._build_snapshot(rows, season_start)

    def _unique_team(self, club_name):
        response = self._get("teams", {"search": club_name})
        candidates = response if isinstance(response, list) else []
        exact = [item.get("team") for item in candidates if isinstance(item, dict) and self._same_name((item.get("team") or {}).get("name"), club_name)]
        return exact[0] if len(exact) == 1 else None

    def _get(self, path, params):
        try:
            response = requests.get(
                f"{API_BASE_URL}/{path}",
                params=params,
                headers={"x-apisports-key": self.api_key},
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except (ValueError, requests.RequestException):
            return None
        if data.get("errors"):
            return None
        return data.get("response")

    def _build_snapshot(self, rows, season_start):
        position = next((self._value(row, "games", "position") for row in rows if self._value(row, "games", "position")), "")
        metrics = self._metrics(rows)
        competitions = []
        for row in rows:
            league = row.get("league") or {}
            name_ar = _COMPETITION_AR.get(league.get("name"))
            if not name_ar:
                continue  # Never force an untranslated competition into an Arabic card.
            competitions.append({"name_ar": name_ar, **self._metrics([row])})
        return {
            "season": f"{season_start}–{season_start + 1}",
            "season_start": season_start,
            "scope": "جميع المسابقات",
            "as_of": self.now_fn().date().isoformat(),
            "position_group": self._position_group(position),
            "metrics": metrics,
            "competitions": competitions,
            "source_url": API_DOCS_URL,
        }

    def _metrics(self, rows):
        return {
            "appearances": self._sum(rows, "games", "appearences"),
            "minutes": self._sum(rows, "games", "minutes"),
            "goals": self._sum(rows, "goals", "total"),
            "assists": self._sum(rows, "goals", "assists"),
            "key_passes": self._sum(rows, "passes", "key"),
            "tackles": self._sum(rows, "tackles", "total"),
            "interceptions": self._sum(rows, "tackles", "interceptions"),
            "blocks": self._sum(rows, "tackles", "blocks"),
            "conceded": self._sum(rows, "goals", "conceded"),
            "saves": self._sum(rows, "goals", "saves"),
        }

    @staticmethod
    def _value(row, group, key):
        value = (row.get(group) or {}).get(key)
        return value if isinstance(value, (int, float)) else None

    def _sum(self, rows, group, key):
        values = [self._value(row, group, key) for row in rows]
        values = [value for value in values if value is not None]
        return sum(values) if values else None

    @staticmethod
    def _position_group(position):
        value = str(position or "").casefold()
        if "goalkeeper" in value or "keeper" in value:
            return "goalkeeper"
        if "defender" in value:
            return "defender"
        if "midfield" in value:
            return "midfielder"
        return "attacker"

    def _fresh(self, cached):
        try:
            fetched = datetime.fromisoformat(cached["fetched_at"].replace("Z", "+00:00"))
        except (AttributeError, KeyError, TypeError, ValueError):
            return False
        return self.now_fn() - fetched < timedelta(days=self.cache_days)

    def _load_cache(self):
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"version": 1, "entries": {}}
        except (OSError, ValueError, TypeError):
            return {"version": 1, "entries": {}}

    def _save_cache(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.cache_path.parent, delete=False) as handle:
            json.dump(self.cache, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            name = handle.name
        Path(name).replace(self.cache_path)

    @staticmethod
    def _norm(value):
        value = unicodedata.normalize("NFKD", str(value or ""))
        value = "".join(char for char in value if not unicodedata.combining(char))
        return re.sub(r"[^\w]+", "", value).casefold()

    def _same_name(self, left, right):
        return bool(self._norm(left)) and self._norm(left) == self._norm(right)
