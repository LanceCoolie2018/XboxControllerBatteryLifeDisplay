#!/usr/bin/env bash
# Live Maintenance Monkey status panel for the Pi desktop.
# Double-click or: ./mm-dashboard.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
cd "$ROOT"
exec python3 -m maintenance_monkey dashboard --cwd "$ROOT" --interval 2
