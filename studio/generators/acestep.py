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
                   safe_name, sleep_with_cancel, unique_path)

LANGS = ["ru", "en", "zh", "ja", "ko", "es", "fr", "de", "it", "pt", "uk", "pl", "tr", "unknown"]


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

    def generate(self, req: GenerationRequest, out_dir: Path, progress=None, cancel=None) -> list[GeneratedTrack]:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ok, status = self.is_available()
        if not ok:
            raise GenerationError(f"ACE-Step недоступен: {status}")
        payload = self.build_payload(req)
        if progress:
            progress(0.02, "ACE-Step: отправка задачи")
        body = self._post("/release_task", payload)
        task_id = (body.get("data") or {}).get("task_id")
        if not task_id:
            raise GenerationError(f"ACE-Step не вернул task_id: {body}")

        t0 = time.time()
        expected = 20 + req.duration * 0.6 * max(1, payload["batch_size"])
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
        title = safe_name(req.title or req.style[:40], "ACE-Step")
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
            metas = r.get("metas") or {}
            t = GeneratedTrack(path=dst, title=name, lyrics=r.get("lyrics") or req.lyrics, engine=self.id,
                               meta={"prompt": r.get("prompt") or req.style, "bpm": metas.get("bpm"),
                                     "key": metas.get("keyscale"), "duration": metas.get("duration"),
                                     "seed": r.get("seed_value"), "dit_model": r.get("dit_model"),
                                     "lm_model": r.get("lm_model"), "task_id": task_id})
            t.save_sidecar()
            tracks.append(t)
        if not tracks:
            raise GenerationError("ACE-Step вернул пустой результат")
        if progress:
            progress(1.0, f"Готово: {len(tracks)} трек(а)")
        return tracks
