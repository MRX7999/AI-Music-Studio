"""Release workspace and publishing queue.

<library>/releases/<id>/
    release.json        state of the release (files, metadata, step results)
    master.wav          export after optional super-resolution (float, export rate)
    cover.jpg, cover_thumb.jpg, lyrics.lrc, lyrics.srt, ai_check.json
    telegram.mp3, youtube.mp4  (made on demand)
<library>/releases/queue.json   publish jobs (pending / running / done / failed / waiting)
<library>/releases/log.jsonl    one line per finished upload with its public link
"""
from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..generators.base import safe_name

MAX_ATTEMPTS = 6


@dataclass
class Release:
    id: str
    title: str
    artist: str = ""
    source: str = ""                  # rendered export the release was created from
    master: str = ""                  # file to publish (after super-resolution, if any)
    cover: str = ""
    thumb: str = ""
    lyrics_text: str = ""
    lrc: str = ""
    srt: str = ""
    ai_report: dict = field(default_factory=dict)
    superres: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)          # genre, language, explicit, tags, description, ai{}
    created: float = field(default_factory=time.time)

    def folder(self, root: Path) -> Path:
        return Path(root) / "releases" / self.id

    def save(self, root: Path) -> Path:
        f = self.folder(root)
        f.mkdir(parents=True, exist_ok=True)
        p = f / "release.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)
        return p

    @classmethod
    def load(cls, root: Path, rid: str) -> "Release":
        p = Path(root) / "releases" / rid / "release.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)

    def to_dict(self) -> dict:
        return asdict(self)


def create(root: Path, source: str | Path, title: str, artist: str = "", lyrics_text: str = "",
           meta: dict | None = None) -> Release:
    source = Path(source)
    rid = time.strftime("%Y%m%d-%H%M%S-") + safe_name(title or source.stem, "release")[:40]
    r = Release(id=rid, title=title or source.stem, artist=artist, source=str(source), lyrics_text=lyrics_text,
                meta=dict(meta or {}))
    r.meta.setdefault("ai", {"generated": True, "vocals": "ai", "music": "ai", "lyrics": "human_or_ai",
                             "tools": []})
    f = r.folder(root)
    f.mkdir(parents=True, exist_ok=True)
    dst = f / ("source" + source.suffix.lower())
    shutil.copy2(source, dst)
    r.source = str(dst)
    r.master = str(dst)
    r.save(root)
    return r


def list_releases(root: Path) -> list[dict]:
    out = []
    base = Path(root) / "releases"
    if not base.exists():
        return out
    for p in sorted(base.glob("*/release.json"), reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append({"id": d["id"], "title": d.get("title"), "artist": d.get("artist"),
                        "created": d.get("created"), "cover": d.get("thumb") or d.get("cover"),
                        "verdict": (d.get("ai_report") or {}).get("verdict")})
        except (OSError, ValueError, KeyError):
            continue
    return out


class PublishQueue:
    """Thread-safe persistent job list. Failed jobs with transient errors wait with exponential
    back-off (2, 4, 8 … min, YouTube quota errors wait until the next day)."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / "releases" / "queue.json"
        self.log_path = self.root / "releases" / "log.jsonl"
        self.lock = threading.Lock()

    def _load(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _save(self, jobs: list[dict]):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def jobs(self) -> list[dict]:
        with self.lock:
            return self._load()

    def add(self, release_id: str, service: str, options: dict) -> dict:
        job = {"id": uuid.uuid4().hex[:12], "release": release_id, "service": service, "options": options,
               "status": "pending", "attempts": 0, "next_try": 0, "error": "", "result": {},
               "created": time.time(), "updated": time.time()}
        with self.lock:
            jobs = self._load()
            jobs.append(job)
            self._save(jobs)
        return job

    def update(self, job_id: str, **changes) -> dict | None:
        with self.lock:
            jobs = self._load()
            for j in jobs:
                if j["id"] == job_id:
                    j.update(changes)
                    j["updated"] = time.time()
                    self._save(jobs)
                    return j
        return None

    def remove(self, job_id: str) -> bool:
        with self.lock:
            jobs = self._load()
            keep = [j for j in jobs if j["id"] != job_id or j["status"] == "running"]
            self._save(keep)
            return len(keep) != len(jobs)

    def due(self, now: float | None = None) -> list[dict]:
        now = now or time.time()
        return [j for j in self.jobs() if j["status"] in ("pending", "waiting") and j["next_try"] <= now]

    def fail(self, job: dict, error: str, permanent: bool, quota: bool = False) -> dict:
        attempts = job["attempts"] + 1
        if permanent or attempts >= MAX_ATTEMPTS:
            return self.update(job["id"], status="failed", attempts=attempts, error=error)
        delay = 24 * 3600 if quota else 60 * 2 ** attempts
        return self.update(job["id"], status="waiting", attempts=attempts, error=error, next_try=time.time() + delay)

    def done(self, job: dict, result: dict) -> dict:
        j = self.update(job["id"], status="done", result=result, error="", attempts=job["attempts"] + 1)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "release": job["release"],
                                 "service": job["service"], **result}, ensure_ascii=False) + "\n")
        return j

    def log(self, limit: int = 200) -> list[dict]:
        try:
            lines = self.log_path.read_text(encoding="utf-8").splitlines()[-limit:]
        except OSError:
            return []
        out = []
        for ln in reversed(lines):
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
        return out
