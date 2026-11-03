"""ACE-Step 1.5 — локальная генерация песен через REST API (по умолчанию http://127.0.0.1:8001).

Сервер запускается из репозитория ACE-Step 1.5 (`uv run acestep-api`), см. docs/ACE_STEP.md.
Протокол: https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/API.md
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import urljoin

import requests

from .base import (GeneratedTrack, GenerationError, GenerationRequest, Generator, check_cancel, download,
                   meta_number, meta_text, safe_name, sleep_with_cancel, unique_path)

EDIT_TASKS = ("repaint", "cover", "extract", "lego", "complete")
BASE_ONLY_TASKS = ("extract", "lego", "complete")   # turbo/SFT models support only repaint and cover
TRACK_NAMES = ["woodwinds", "brass", "fx", "synth", "strings", "percussion", "keyboard", "guitar", "bass", "drums",
               "backing_vocals", "vocals"]

LANGS = ["ru", "en", "zh", "ja", "ko", "es", "fr", "de", "it", "pt", "uk", "pl", "tr", "unknown"]


def _seed_of(seed_value, index: int):
    """ACE-Step reports the seeds of a batch as one string "11,22,33"; variant i gets its own seed."""
    if seed_value is None or isinstance(seed_value, bool):
        return None
    if isinstance(seed_value, (int, float)):
        return int(seed_value)
    parts = [p.strip() for p in str(seed_value).split(",") if p.strip()]
    if not parts:
        return None
    p = parts[index] if index < len(parts) else parts[0]
    return int(p) if p.lstrip("-").isdigit() else p


class AceStepGenerator(Generator):
    id = "acestep"
    name = "ACE-Step 1.5 (локально)"
    description = ("Открытая модель (MIT), работает на Mac M-серии через MPS/MLX. "
                   "Песни с вокалом до 10 минут, 50+ языков. Нужен запущенный acestep-api.")
    local = True

    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: int = 15):
        self.base_url = (base_url or os.environ.get("ACESTEP_API_URL") or "http://127.0.0.1:8001").rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("ACESTEP_API_KEY", "")
        self.timeout = timeout
        self._models_cache: list[dict] | None = None

    # ── HTTP ─────────────────────────────────────────────────
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _get(self, path: str, **kw):
        r = requests.get(self.base_url + path, headers=self._headers(), timeout=self.timeout, **kw)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, payload: dict):
        r = requests.post(self.base_url + path, headers=self._headers(), json=payload, timeout=self.timeout)
        if r.status_code >= 400:
            raise GenerationError(f"ACE-Step {path}: HTTP {r.status_code} {r.text[:300]}")
        body = r.json()
        if body.get("code") not in (None, 200) or body.get("error"):
            raise GenerationError(f"ACE-Step {path}: {body.get('error') or body}")
        return body

    # ── интерфейс ────────────────────────────────────────────
    def is_available(self) -> tuple[bool, str]:
        try:
            body = self._get("/health")
            st = (body.get("data") or {}).get("status")
            if st == "ok":
                return True, f"сервер доступен: {self.base_url}"
            return False, f"сервер ответил: {st}"
        except requests.RequestException as e:
            return False, f"нет соединения с {self.base_url} ({e.__class__.__name__}). Запустите acestep-api"

    def models(self) -> list[dict]:
        try:
            data = self._get("/v1/models").get("data") or {}
            self._models_cache = [{"id": m["name"], "name": m["name"] + (" (по умолчанию)" if m.get("is_default") else ""),
                                   "default": bool(m.get("is_default"))} for m in data.get("models", [])]
        except (requests.RequestException, KeyError, ValueError):
            self._models_cache = self._models_cache or []
        return self._models_cache

    def param_schema(self, model: str = "") -> list[dict]:
        base = "base" in (model or "") and "turbo" not in (model or "")
        return [
            {"key": "inference_steps", "label": "Шаги диффузии", "type": "number", "default": 50 if base else 8,
             "min": 1, "max": 200 if base else 20, "integer": True},
            {"key": "guidance_scale", "label": "Guidance (только base)", "type": "number", "default": 7.0,
             "min": 1.0, "max": 15.0},
            {"key": "thinking", "label": "LM-«размышление» (лучше структура, медленнее)", "type": "boolean",
             "default": True},
            {"key": "audio_format", "label": "Формат с сервера", "type": "enum", "default": "flac",
             "options": ["flac", "wav", "mp3"]},
        ]

    def build_payload(self, req: GenerationRequest) -> dict:
        lyrics = "[Instrumental]" if req.instrumental else (req.lyrics or "")
        prompt = req.style.strip()
        payload = {
            "prompt": prompt,
            "lyrics": lyrics,
            "audio_duration": float(min(max(req.duration, 10), 600)),
            "vocal_language": req.language if req.language in LANGS else "unknown",
            "batch_size": int(min(max(req.variations, 1), 8)),
            "time_signature": req.time_signature or "",
            "use_random_seed": req.seed is None,
            "seed": int(req.seed) if req.seed is not None else -1,
            "inference_steps": 8,
            "guidance_scale": 7.0,
            "thinking": True,
            "audio_format": "flac",
        }
        if req.bpm:
            payload["bpm"] = int(min(max(req.bpm, 30), 300))
        if req.key:
            payload["key_scale"] = req.key
        if req.model:
            payload["model"] = req.model
        for k, v in (req.extra or {}).items():
            if v is not None and v != "":
                payload[k] = v
        if isinstance(payload.get("inference_steps"), float):
            payload["inference_steps"] = int(payload["inference_steps"])
        return payload

    def _post_form(self, path: str, payload: dict, files: dict):
        """multipart/form-data: file uploads (src_audio / reference_audio) + every field as text."""
        h = {k: v for k, v in self._headers().items() if k != "Content-Type"}
        data = {k: (json.dumps(v) if isinstance(v, (list, dict)) else
                    ("true" if v is True else "false" if v is False else str(v)))
                for k, v in payload.items() if v is not None}
        opened = {k: (Path(p).name, open(p, "rb")) for k, p in files.items()}
        try:
            r = requests.post(self.base_url + path, headers=h, data=data, files=opened, timeout=max(self.timeout, 300))
        finally:
            for _, fh in opened.values():
                fh.close()
        if r.status_code >= 400:
            raise GenerationError(f"ACE-Step {path}: HTTP {r.status_code} {r.text[:300]}")
        body = r.json()
        if body.get("code") not in (None, 200) or body.get("error"):
            raise GenerationError(f"ACE-Step {path}: {body.get('error') or body}")
        return body

    def generate(self, req: GenerationRequest, out_dir: Path, progress=None, cancel=None) -> list[GeneratedTrack]:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ok, status = self.is_available()
        if not ok:
            raise GenerationError(f"ACE-Step недоступен: {status}")
        payload = self.build_payload(req)
        title = safe_name(req.title or req.style[:40], "ACE-Step")
        expected = 20 + req.duration * 0.6 * max(1, payload["batch_size"])
        return self._run_task(payload, {}, out_dir, title, req.lyrics, req.style, expected, progress, cancel)

    def _run_task(self, payload: dict, files: dict, out_dir: Path, title: str, lyrics: str, style: str,
                  expected: float, progress, cancel, extra_meta: dict | None = None) -> list[GeneratedTrack]:
        if progress:
            progress(0.02, "ACE-Step: отправка задачи")
        body = self._post_form("/release_task", payload, files) if files else self._post("/release_task", payload)
        task_id = (body.get("data") or {}).get("task_id")
        if not task_id:
            raise GenerationError(f"ACE-Step не вернул task_id: {body}")

        t0 = time.time()
        results = None
        while True:
            check_cancel(cancel)
            q = self._post("/query_result", {"task_id_list": [task_id]})
            items = q.get("data") or []
            item = next((i for i in items if i.get("task_id") == task_id), items[0] if items else None)
            st = item.get("status") if item else 0
            if st == 1:
                raw = item.get("result") or "[]"
                results = json.loads(raw) if isinstance(raw, str) else raw
                break
            if st == 2:
                raise GenerationError(f"ACE-Step: генерация не удалась: {item.get('result') or item}")
            el = time.time() - t0
            if progress:
                progress(min(0.05 + 0.85 * el / expected, 0.9), f"ACE-Step: генерация… {el:.0f} с")
            if el > 3600:
                raise GenerationError("ACE-Step: превышено время ожидания (60 мин)")
            sleep_with_cancel(2.0, cancel)

        tracks = []
        for i, r in enumerate(results or []):
            if r.get("status") == 2 or not r.get("file"):
                continue
            url = r["file"] if r["file"].startswith("http") else urljoin(self.base_url + "/", r["file"].lstrip("/"))
            ext = "." + payload.get("audio_format", "flac").replace("wav32", "wav")
            name = title if len(results) == 1 else f"{title} — вариант {i + 1}"
            dst = unique_path(out_dir / f"{name}{ext}")
            if progress:
                progress(0.92 + 0.07 * i / max(len(results), 1), f"Загрузка: {dst.name}")
            download(url, dst, headers=self._headers(), cancel=cancel)
            metas = r.get("metas") if isinstance(r.get("metas"), dict) else {}
            # cover/repaint run without the LM: bpm, duration and key come back as "N/A"
            bpm = meta_number(metas.get("bpm")) or meta_number(r.get("bpm"))
            meta = {"prompt": r.get("prompt") or style, "bpm": int(round(bpm)) if bpm else None,
                    "key": meta_text(metas.get("keyscale")) or meta_text(r.get("keyscale")),
                    "duration": meta_number(metas.get("duration")) or meta_number(r.get("duration")),
                    "time_signature": meta_text(metas.get("timesignature")),
                    "seed": _seed_of(r.get("seed_value"), i), "dit_model": r.get("dit_model"),
                    "lm_model": r.get("lm_model"), "task_id": task_id,
                    "task_type": payload.get("task_type", "text2music")}
            meta.update(extra_meta or {})
            t = GeneratedTrack(path=dst, title=name, lyrics=r.get("lyrics") or lyrics, engine=self.id, meta=meta)
            t.save_sidecar()
            tracks.append(t)
        if not tracks:
            raise GenerationError("ACE-Step вернул пустой результат")
        if progress:
            progress(1.0, f"Готово: {len(tracks)} трек(а)")
        return tracks

    # ── редактирование готовой песни (любого источника: ACE-Step, Suno/GPTunneL, свой файл) ──
    def build_edit_payload(self, task: str, start: float = 0.0, end: float = -1.0, prompt: str = "",
                           lyrics: str = "", track: str = "", track_classes: list | None = None,
                           strength: float | None = None, repaint_mode: str = "balanced",
                           repaint_strength: float = 0.5, model: str = "", seed: int | None = None,
                           steps: int | None = None, variations: int = 1, audio_format: str = "flac",
                           language: str = "unknown", duration: float | None = None) -> dict:
        if task not in EDIT_TASKS:
            raise GenerationError(f"ACE-Step: неизвестная задача {task}")
        if task in BASE_ONLY_TASKS and model and "base" not in model:
            raise GenerationError(f"ACE-Step: «{task}» работает только с base-моделью (не turbo/SFT)")
        if task == "repaint" and end != -1 and end <= start:
            raise GenerationError("ACE-Step: конец фрагмента должен быть позже начала")
        p = {
            "task_type": task, "prompt": prompt, "lyrics": lyrics,
            "batch_size": int(min(max(variations, 1), 4)), "audio_format": audio_format,
            "use_random_seed": seed is None, "seed": int(seed) if seed is not None else -1,
            "vocal_language": language if language in LANGS else "unknown",
            "thinking": False,
        }
        if steps:
            p["inference_steps"] = int(steps)
        if model:
            p["model"] = model
        if duration:
            p["audio_duration"] = float(duration)
        if task == "repaint":
            p.update({"repainting_start": float(max(start, 0.0)), "repainting_end": float(end),
                      "repaint_mode": repaint_mode if repaint_mode in ("conservative", "balanced", "aggressive")
                      else "balanced", "repaint_strength": float(min(max(repaint_strength, 0.0), 1.0)),
                      "chunk_mask_mode": "explicit", "repaint_wav_crossfade_sec": 0.25})
        if task == "cover":
            p["audio_cover_strength"] = float(min(max(strength if strength is not None else 0.5, 0.0), 1.0))
        if task in ("extract", "lego"):
            if track and track not in TRACK_NAMES:
                raise GenerationError(f"ACE-Step: дорожка {track} не из списка {', '.join(TRACK_NAMES)}")
            if track:
                p["track_name"] = track
        if task == "complete" and track_classes:
            p["track_classes"] = [t for t in track_classes if t in TRACK_NAMES]
        return p

    def edit(self, src: str | Path, task: str, out_dir: Path, title: str = "", progress=None, cancel=None,
             **kw) -> list[GeneratedTrack]:
        src = Path(src)
        if not src.exists():
            raise GenerationError(f"Нет файла {src}")
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ok, status = self.is_available()
        if not ok:
            raise GenerationError(f"ACE-Step недоступен: {status}")
        payload = self.build_edit_payload(task, **kw)
        label = {"repaint": "перегенерация", "cover": "кавер", "extract": "извлечение", "lego": "новая дорожка",
                 "complete": "дополнение"}[task]
        name = safe_name(title or src.stem, "ACE-Step") + f" — {label}"
        if task == "repaint":
            e = kw.get("end", -1)
            name += f" {kw.get('start', 0):.0f}-{'конец' if e == -1 else f'{e:.0f}'}с"
        if task in ("extract", "lego") and kw.get("track"):
            name += f" {kw['track']}"
        extra = {"source": str(src), "edit": {k: v for k, v in payload.items() if k not in ("lyrics", "prompt")}}
        return self._run_task(payload, {"src_audio": src}, out_dir, name, kw.get("lyrics", ""), kw.get("prompt", ""),
                              90.0, progress, cancel, extra)
