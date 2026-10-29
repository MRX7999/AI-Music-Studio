"""Папка проектов с запасными вариантами.

macOS может запретить процессу доступ к ~/Music (защита TCC: «Operation not permitted»),
поэтому при ошибке берём следующую доступную папку, а не падаем при старте.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

DEFAULT_ROOT = Path.home() / "Music" / "AI Music Studio"
FALLBACKS = (Path.home() / "AI Music Studio", Path(tempfile.gettempdir()) / "AI Music Studio")

_cache: dict[str, tuple[Path, str]] = {}


def _usable(p: Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".ams_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return os.access(p, os.W_OK)
    except OSError:
        return False


def resolve_root(preferred: str | os.PathLike | None) -> tuple[Path, str]:
    """→ (папка, предупреждение). Предупреждение пустое, если взята нужная папка."""
    want = Path(preferred).expanduser() if preferred else DEFAULT_ROOT
    key = str(want)
    if key in _cache and _cache[key][0].is_dir():
        return _cache[key]
    for cand in (want, DEFAULT_ROOT, *FALLBACKS):
        if _usable(cand):
            note = "" if cand == want else (f"нет доступа к «{want}» (macOS: Настройки → Конфиденциальность → "
                                           f"Файлы и папки), используется «{cand}»")
            _cache[key] = (cand, note)
            return cand, note
    raise OSError(f"Нет доступной для записи папки проектов (пробовали {want} и запасные варианты)")


def project_root(settings) -> Path:
    return resolve_root(settings.value("output_dir", "") or None)[0]


def root_warning(settings) -> str:
    return resolve_root(settings.value("output_dir", "") or None)[1]
