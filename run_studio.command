#!/usr/bin/env bash
# Двойной клик в Finder запускает AI Music Studio. Подхватывает .env и .venv, если они есть.
cd "$(dirname "$0")"
if [[ -f .env ]]; then set -a; source .env; set +a; fi
if [[ -x .venv/bin/python ]]; then PY=.venv/bin/python; else PY="${PYTHON:-python3}"; fi
exec "$PY" studio_app.py "$@"
