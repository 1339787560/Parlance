#!/bin/sh
# infoServer launcher (macOS / Linux) — cross-platform entry via start.py
# Double-click in Finder, or run from terminal: ./start.command [args]

cd "$(dirname "$0")" || exit 1

VENV_PYTHON=".venv/bin/python"
if [ -x "$VENV_PYTHON" ]; then
    exec "$VENV_PYTHON" start.py "$@"
elif command -v uv >/dev/null 2>&1; then
    exec uv run python start.py "$@"
else
    exec python3 start.py "$@"
fi
