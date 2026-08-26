import json

import bot.fast_monitor as fast_monitor
from bot.fast_monitor import run_once


def test_fast_monitor_runs_the_shared_bot_logic_without_git_sync():
    calls = []

    changed = run_once(sync_git=False, main_fn=lambda: calls.append("ran"))

    assert calls == ["ran"]
    assert changed is False


def test_fast_monitor_uses_fast_mode_when_calling_the_shared_entrypoint(monkeypatch):
    modes = []
    monkeypatch.setattr(fast_monitor.bot_main, "main", lambda fast_mode=False: modes.append(fast_mode))

    run_once(sync_git=False)

    assert modes == [True]


def test_fast_monitor_can_write_a_heartbeat_for_the_fallback_scheduler(tmp_path, monkeypatch):
    heartbeat = tmp_path / "fast_monitor.json"
    monkeypatch.setattr(fast_monitor, "HEARTBEAT_PATH", heartbeat)

    run_once(sync_git=False, main_fn=lambda: None, heartbeat_interval=75)

    data = json.loads(heartbeat.read_text(encoding="utf-8"))
    assert data["runner"] == "fast_monitor"
    assert data["interval_seconds"] == 75
    assert data["updated_at"]
