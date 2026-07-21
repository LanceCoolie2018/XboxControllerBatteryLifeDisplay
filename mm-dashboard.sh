#!/usr/bin/env bash
# Live Maintenance Monkey status panel for the Pi desktop.
# Keeps the window open if something fails so you can read the error.
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
cd "$ROOT" || {
  echo "Cannot cd to $ROOT"
  read -r -p "Press Enter to close..."
  exit 1
}

echo "Starting Maintenance Monkey dashboard..."
echo "  project: $ROOT"
echo "  python:  $(command -v python3)"
echo

# Prefer the package in this repo
if ! python3 -c "import maintenance_monkey" 2>/dev/null; then
  echo "ERROR: cannot import maintenance_monkey"
  echo "PYTHONPATH=$PYTHONPATH"
  read -r -p "Press Enter to close..."
  exit 1
fi

if ! python3 -m maintenance_monkey dashboard --help >/dev/null 2>&1; then
  echo "ERROR: 'dashboard' command missing from maintenance_monkey."
  echo "Available commands:"
  python3 -m maintenance_monkey --help 2>&1 | tail -20
  read -r -p "Press Enter to close..."
  exit 1
fi

# Run dashboard; if it exits with an error, pause
python3 -m maintenance_monkey dashboard --cwd "$ROOT" --interval 2
rc=$?
if [ "$rc" -ne 0 ] && [ "$rc" -ne 130 ]; then
  echo
  echo "Dashboard exited with code $rc"
  read -r -p "Press Enter to close..."
fi
exit "$rc"
