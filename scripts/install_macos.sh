#!/usr/bin/env bash
# Установка AI Music Studio на macOS: venv в .venv, зависимости ядра, проверка ffmpeg.
#   ./scripts/install_macos.sh            # ядро
#   ./scripts/install_macos.sh --ml       # + Demucs, AudioSR, Whisper, librosa
# Ничего не ставит глобально; удалить — rm -rf .venv
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-}"
if [[ -z "$PY" ]]; then
  for c in python3.12 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
  done
fi
[[ -n "$PY" ]] || { echo "Python 3.10–3.12 не найден. Установите: brew install python@3.11"; exit 1; }
VER="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
case "$VER" in 3.10|3.11|3.12) ;; *) echo "Нужен Python 3.10–3.12, найден $VER ($PY). Задайте PYTHON=/путь/к/python3.11"; exit 1;; esac

echo "Python: $PY ($VER)"
[[ -d .venv ]] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
if [[ "${1:-}" == "--ml" ]]; then
  .venv/bin/python -m pip install -r requirements-ml.txt
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ВНИМАНИЕ: ffmpeg не найден — M4A/ALAC/MP3 не будут работать. Установите: brew install ffmpeg"
fi

AMS_SMOKE=1 .venv/bin/python studio_app.py && echo "Готово. Запуск: ./run_studio.command или .venv/bin/python studio_app.py"
