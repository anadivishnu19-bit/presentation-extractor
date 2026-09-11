#!/usr/bin/env bash
# Double-clickable (via Finder "Open With Terminal") or run: ./start.sh
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Setting up (first run only)..."
  python3 -m venv .venv
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -r requirements.txt
fi

echo "Starting Presentation Extractor..."
echo "Opening http://localhost:8000 in your browser."
./.venv/bin/python app.py
