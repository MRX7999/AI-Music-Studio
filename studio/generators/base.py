"""Общий интерфейс движков генерации песен."""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import requests


class GenerationError(RuntimeError):
    pass


class GenerationCancelled(GenerationError):
    pass


@dataclass
class GenerationRequest:
    title: str = ""
    style: str = ""                 # жанр, настроение, инструменты, вокал
    lyrics: str = ""                # текст с тегами [Verse] [Chorus] …
    instrumental: bool = False
    duration: float = 120.0         # секунды
    bpm: int | None = None
    key: str = ""                   # например "C major", "A minor"
    time_signature: str = "4"       # 2/3/4/6 (ACE-Step)
    language: str = "ru"
    seed: int | None = None
    variations: int = 1
    model: str = ""                 # выбранная модель движка
    extra: dict = field(default_factory=dict)   # параметры конкретного движка


@dataclass
class GeneratedTrack:
    path: Path
    title: str
    lyrics: str = ""
    cover: Path | None = None
    engine: str = ""
    meta: dict = field(default_factory=dict)
    stems: dict = field(default_factory=dict)   # {stem: Path}, если движок отдаёт стемы

    def to_dict(self, base_dir: Path | None = None) -> dict:
        """Пути — относительно base_dir (папки sidecar-файла), чтобы папку с песней можно было переносить."""
        def rel(p):
            if p is None:
                return None
            p = Path(p)
            if base_dir is not None:
                try:
                    return str(p.resolve().relative_to(Path(base_dir).resolve()))
                except ValueError:
                    pass
            return str(p.resolve())
        d = asdict(self)
        d["path"] = rel(self.path)
        d["cover"] = rel(self.cover)
        d["stems"] = {k: rel(v) for k, v in self.stems.items()}
        return d

    def save_sidecar(self) -> Path:
        side = self.path.with_suffix(".json")
        side.write_text(json.dumps(self.to_dict(side.parent), ensure_ascii=False, indent=2), encoding="utf-8")
        return side

    @classmethod
    def from_sidecar(cls, side: str | Path) -> "GeneratedTrack":
        """Читает <песня>.json; относительные пути разрешаются от папки файла."""
        side = Path(side)
        d = json.loads(side.read_text(encoding="utf-8"))

        def res(v):
            if not v:
                return None
            p = Path(v)
            return p if p.is_absolute() else (side.parent / p).resolve()
        path = res(d.get("path")) or side.with_suffix(".wav")
        return cls(path=path, title=d.get("title") or path.stem, lyrics=d.get("lyrics") or "",
                   cover=res(d.get("cover")), engine=d.get("engine") or "", meta=dict(d.get("meta") or {}),
                   stems={k: res(v) for k, v in (d.get("stems") or {}).items() if v})


class Generator:
    id = "base"
    name = "Base"
    description = ""
    local = False

    def is_available(self) -> tuple[bool, str]:
        """→ (готов ли, человеко-читаемый статус)."""
        return False, "не реализовано"

    def models(self) -> list[dict]:
        return []

    def param_schema(self, model: str = "") -> list[dict]:
        """Дополнительные поля формы: [{key, label, type: enum|number|boolean|string, default, options, min, max}]."""
        return []

    def estimate_price(self, req: GenerationRequest) -> str | None:
        return None

    def generate(self, req: GenerationRequest, out_dir: Path, progress=None, cancel=None) -> list[GeneratedTrack]:
        raise NotImplementedError


# ── утилиты ───────────────────────────────────────────────────

def safe_name(s: str, fallback: str = "track") -> str:
    s = re.sub(r"[\\/:*?\"<>|\n\r\t]+", " ", s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return (s[:80] or fallback).strip(" .")


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(2, 1000):
        p = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not p.exists():
            return p
    return path.with_name(f"{path.stem}-{int(time.time())}{path.suffix}")


def download(url: str, dst: Path, headers: dict | None = None, timeout: int = 120, cancel=None) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, headers=headers or {}, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        tmp = dst.with_suffix(dst.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                if cancel and cancel():
                    f.close()
                    tmp.unlink(missing_ok=True)
                    raise GenerationCancelled("Отменено")
                f.write(chunk)
        tmp.replace(dst)
    return dst


def check_cancel(cancel):
    if cancel and cancel():
        raise GenerationCancelled("Отменено пользователем")


def sleep_with_cancel(seconds: float, cancel=None):
    end = time.time() + seconds
    while time.time() < end:
        check_cancel(cancel)
        time.sleep(min(0.2, max(0.0, end - time.time())))
