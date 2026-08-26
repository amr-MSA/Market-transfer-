#!/usr/bin/env bash
set -euo pipefail

# Run from the repository root on a computer that stays online. Secrets belong
# in .env and are never committed. Git synchronization makes the monitor share
# the same delivery state with the GitHub Actions fallback.
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec python3 -m bot.fast_monitor --interval 75 --sync-git
