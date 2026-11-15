#!/usr/bin/env bash
# Codespaces: fetch live data once, then serve the real cards on port 8000.
set -e
cd "$(dirname "$0")/.."
python tools/live_check.py || echo "(live_check reported problems: the preview shows whatever did load)"
python tools/preview.py --serve
