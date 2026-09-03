"""Run the transfer bot frequently on a persistent host.

GitHub Actions remains a fallback, but its schedule is best-effort. This
monitor is meant for a machine or service that stays online and can check the
primary Fabrizio source every 60–90 seconds. It deliberately reuses
``bot.main.main`` so parsing, delivery tracking, source verification and the
strict identity policy remain exactly the same in both execution paths.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import main as bot_main


ROOT = Path(__file__).resolve().parents[1]
STATE_PATHS = [
    "data/transfers.json",
    "data/bot_updates.json",
    "data/news.json",
    "data/media_library.json",
    "data/identity_cards.json",
    "data/image_review.json",
    "config/channels.json",
    "config/settings.json",
    "data/fast_monitor.json",
]
HEARTBEAT_PATH = ROOT / "data/fast_monitor.json"


def _git(*args, check=True):
    return subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True, check=check
    )


def _has_state_changes():
    result = _git("diff", "--quiet", "--", *STATE_PATHS, check=False)
    return result.returncode != 0


def sync_before_run():
    """Fast-forward state before reading it; never merge unknown JSON blindly."""
    _git("pull", "--ff-only", "origin", "main")


def persist_state():
    if not _has_state_changes():
        return False
    _git("config", "user.name", "transfer-fast-monitor")
    _git("config", "user.email", "monitor@localhost")
    _git("add", *STATE_PATHS)
    _git("commit", "-m", "chore: update fast monitor state")
    _git("push", "origin", "HEAD:main")
    return True


def _write_heartbeat(interval_seconds):
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_PATH.write_text(json.dumps({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "interval_seconds": int(interval_seconds),
        "runner": "fast_monitor",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_once(sync_git=False, main_fn=None, heartbeat_interval=None):
    """Run one safe polling cycle; exposed for tests and one-shot use."""
    if sync_git:
        sync_before_run()
    if main_fn:
        main_fn()
    else:
        bot_main.main(fast_mode=True)
    if heartbeat_interval is not None:
        _write_heartbeat(heartbeat_interval)
    if sync_git:
        return persist_state()
    return False


def run_forever(interval_seconds=75, sync_git=False, main_fn=None, sleep_fn=time.sleep):
    interval_seconds = max(60, int(interval_seconds))
    heartbeat_every_seconds = 240
    last_heartbeat = 0.0
    lock_path = ROOT / ".fast-monitor.lock"
    with lock_path.open("w") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("fast monitor is already running on this host") from exc
        while True:
            started = time.monotonic()
            try:
                heartbeat_due = sync_git and started - last_heartbeat >= heartbeat_every_seconds
                changed = run_once(
                    sync_git=sync_git,
                    main_fn=main_fn,
                    heartbeat_interval=interval_seconds if heartbeat_due else None,
                )
                if heartbeat_due:
                    last_heartbeat = started
                print(f"[fast-monitor] cycle complete state_changed={changed}")
            except Exception as exc:  # Keep monitoring after one transient failure.
                print(f"[fast-monitor] cycle failed: {exc}", file=sys.stderr)
            elapsed = time.monotonic() - started
            sleep_fn(max(1, interval_seconds - elapsed))


def cli(argv=None):
    parser = argparse.ArgumentParser(description="Fast persistent monitor for the Fabrizio primary source.")
    parser.add_argument("--interval", type=int, default=75, help="Polling interval in seconds; minimum is 60.")
    parser.add_argument("--once", action="store_true", help="Run a single polling cycle and exit.")
    parser.add_argument("--sync-git", action="store_true", help="Fast-forward/persist shared JSON state through origin/main.")
    args = parser.parse_args(argv)
    if args.once:
        run_once(sync_git=args.sync_git)
        return
    run_forever(interval_seconds=args.interval, sync_git=args.sync_git)


if __name__ == "__main__":
    cli()
