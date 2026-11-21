#!/bin/bash
# Run the Web demo with this checkout's isolated Python environment.
set -eu
ROOT="$(dirname "$(dirname "$(readlink -f "$0")")")"
PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    printf 'Missing project environment: %s\n' "$PYTHON" >&2
    printf 'From %s run: python3 -m venv .venv && source .venv/bin/activate && python -m pip install -r requirements.txt\n' "$ROOT" >&2
    exit 1
fi
cd "$ROOT"
exec "$PYTHON" "$ROOT/demo/app.py" "$@"
