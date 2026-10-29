"""Suno и другие музыкальные модели через GPTunneL Creative Lab API v2 (облако, платно).

Документация:
  https://docs.gptunnel.ru/creative-lab/models/
  https://docs.gptunnel.ru/creative-lab/create-task/
  https://docs.gptunnel.ru/creative-lab/get-task/
Ключ: переменная окружения GPTUNNEL_API_KEY (заголовок `Authorization: <ключ>` без Bearer).
Ссылки на результат живут ограниченное время — файлы скачиваются сразу.
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import requests

from .base import (GeneratedTrack, GenerationError, GenerationRequest, Generator, check_cancel, download,
                   safe_name, sleep_with_cancel, unique_path)

API = "https://gptunnel.ru/api/v2/media"
MUSIC_TYPES = {"MUSIC", "AUDIO", "SONG"}

# какие ключи схемы модели считаем «текстом», «стилем» и т.д. (схема приходит с сервера)
LYRICS_KEYS = ("lyrics", "lyric", "text", "song_lyrics")
STYLE_KEYS = ("style", "tags", "styles", "genre")
TITLE_KEYS = ("title", "name", "song_title")
INSTR_KEYS = ("instrumental", "make_instrumental", "is_instrumental")
DURATION_KEYS = ("duration", "audio_duration", "length")


class GptunnelGenerator(Generator):
    id = "gptunnel"
    name = "Suno через GPTunneL (облако)"
    description = ("Модели Suno и др. через Creative Lab API v2. Платно, ключ GPTUNNEL_API_KEY. "
                   "Suno отдаёт 2 варианта на задачу.")
    local = False

    def __init__(self, api_key: str | None = None, base: str = API, timeout: int = 30):
        self.api_key = api_key if api_key is not None else os.environ.get("GPTUNNEL_API_KEY", "")
        self.base = base.rstrip("/")
        self.timeout = timeout
        self._models: list[dict] | None = None

    def _headers(self) -> dict:
        return {"Authorization": self.api_key, "Content-Type": "application/json"}

    def _check(self, r: requests.Response) -> dict:
        try:
            body = r.json()
        except ValueError:
            body = {"raw": r.text[:300]}
        if r.status_code >= 400 or (isinstance(body, dict) and body.get("code") not in (None, 0)):
            msg = body.get("message") or body.get("error") or body.get("details") or body
            raise GenerationError(f"GPTunneL: HTTP {r.status_code}, code {body.get('code')}: {msg}")
        return body

    # ── каталог ──────────────────────────────────────────────
    def is_available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "нет ключа: задайте GPTUNNEL_API_KEY или введите ключ в настройках"
        try:
            ms = self.models(refresh=True)
        except GenerationError as e:
            return False, str(e)
        except requests.RequestException as e:
            return False, f"нет соединения с gptunnel.ru ({e.__class__.__name__})"
        if not ms:
            return False, "ключ принят, но музыкальных моделей в каталоге нет"
        return True, f"доступно моделей: {len(ms)}"

    def models(self, refresh: bool = False) -> list[dict]:
        if self._models is not None and not refresh:
            return self._models
        if not self.api_key:
            return []
        r = requests.get(f"{self.base}/models", headers=self._headers(), timeout=self.timeout)
        body = self._check(r)
        out = []
        for m in body.get("models", []):
            mtype = str(m.get("type", "")).upper()
            mid = m.get("id") or m.get("code")
            if mtype in MUSIC_TYPES or "suno" in str(mid).lower():
                out.append({"id": mid, "name": f"{mid} · {m.get('price', '?')} ₽/{m.get('price_unit', 'gen')}",
                            "price": m.get("price"), "price_unit": m.get("price_unit"),
                            "prompt": m.get("prompt", "optional"), "params": m.get("params") or [],
                            "type": mtype})
        out.sort(key=lambda x: (0 if "suno" in str(x["id"]).lower() else 1, str(x["id"])))
        self._models = out
        return out

    def _model(self, model_id: str) -> dict | None:
        for m in self.models():
            if m["id"] == model_id:
                return m
        return None

    def param_schema(self, model: str = "") -> list[dict]:
        m = self._model(model) if model else None
        if not m:
            return []
        fields = []
        for p in m["params"]:
            key = p.get("key")
            if not key or key in LYRICS_KEYS + STYLE_KEYS + TITLE_KEYS + INSTR_KEYS:
                continue  # эти поля заполняются из основной формы
            f = {"key": key, "label": p.get("label") or key, "type": p.get("type", "string"),
                 "default": p.get("default")}
            if f["type"] == "enum":
                f["options"] = [o.get("value") if isinstance(o, dict) else o for o in p.get("options", [])]
                f["option_labels"] = [o.get("label", o.get("value")) if isinstance(o, dict) else str(o)
                                      for o in p.get("options", [])]
            if f["type"] == "number":
                f.update({k: p[k] for k in ("min", "max", "step", "integer", "unit") if k in p})
            fields.append(f)
        return fields

    # ── запрос ───────────────────────────────────────────────
    def build_body(self, req: GenerationRequest, model_id: str) -> dict:
        m = self._model(model_id) or {"params": [], "prompt": "optional"}
        keys = {p.get("key"): p for p in m["params"] if p.get("key")}

        def first(cands):
            return next((k for k in cands if k in keys), None)

        params: dict = {}
        k_lyr, k_sty, k_tit, k_ins, k_dur = (first(LYRICS_KEYS), first(STYLE_KEYS), first(TITLE_KEYS),
                                             first(INSTR_KEYS), first(DURATION_KEYS))
        prompt_parts = []
        if k_sty and req.style:
            params[k_sty] = req.style
        elif req.style:
            prompt_parts.append(req.style)
        if not req.instrumental and req.lyrics:
            if k_lyr:
                params[k_lyr] = req.lyrics
            else:
                prompt_parts.append(req.lyrics)
        if k_tit and req.title:
            params[k_tit] = req.title
        if k_ins:
            params[k_ins] = bool(req.instrumental)
        elif req.instrumental:
            prompt_parts.append("instrumental, no vocals")
        if k_dur and req.duration:
            spec = keys[k_dur]
            d = req.duration
            if "max" in spec:
                d = min(d, spec["max"])
            if "min" in spec:
                d = max(d, spec["min"])
            params[k_dur] = int(d) if spec.get("integer") else d
        for k, v in (req.extra or {}).items():
            if v is not None and v != "":
                params[k] = v
        body = {"model": model_id, "params": params, "idempotency_key": f"ams-{uuid.uuid4().hex}"}
        if m.get("prompt") != "none":
            body["prompt"] = "\n\n".join(p for p in prompt_parts if p).strip() or (req.title or "song")
        return body

    def estimate_price(self, req: GenerationRequest) -> str | None:
        model_id = req.model or (self.models()[0]["id"] if self.models() else "")
        if not model_id:
            return None
        body = self.build_body(req, model_id)
        body.pop("idempotency_key", None)
        try:
            r = requests.post(f"{self.base}/price", headers=self._headers(), json=body, timeout=self.timeout)
            data = self._check(r)
            price = data.get("price", data.get("total"))
            return f"{price} ₽ за задачу" if price is not None else str(data)
        except (GenerationError, requests.RequestException) as e:
            m = self._model(model_id)
            if m and m.get("price") is not None:
                return f"≈ {m['price']} ₽ ({m.get('price_unit')}) — по каталогу; точный расчёт: {e}"
            return f"не удалось рассчитать: {e}"

    def generate(self, req: GenerationRequest, out_dir: Path, progress=None, cancel=None) -> list[GeneratedTrack]:
        if not self.api_key:
            raise GenerationError("Нет ключа GPTUNNEL_API_KEY")
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        model_id = req.model or (self.models()[0]["id"] if self.models() else "suno")
        tracks: list[GeneratedTrack] = []
        runs = max(1, int(req.variations // 2 + req.variations % 2)) if "suno" in model_id.lower() \
            else max(1, int(req.variations))
        for run in range(runs):
            body = self.build_body(req, model_id)
            if progress:
                progress(0.02 + 0.9 * run / runs, f"GPTunneL: создание задачи {run + 1}/{runs} ({model_id})")
            r = requests.post(f"{self.base}/tasks", headers=self._headers(), json=body, timeout=self.timeout)
            task = self._check(r)
            task_id = task.get("id")
            if not task_id:
                raise GenerationError(f"GPTunneL не вернул id задачи: {task}")
            ignored = task.get("ignored_params")
            t0 = time.time()
            while task.get("status") not in ("done", "failed"):
                check_cancel(cancel)
                sleep_with_cancel(4.0, cancel)
                r = requests.get(f"{self.base}/tasks/{task_id}", headers=self._headers(), timeout=self.timeout)
                task = self._check(r)
                el = time.time() - t0
                if progress:
                    frac = (run + min(el / 150.0, 0.9)) / runs
                    progress(0.02 + 0.9 * frac, f"GPTunneL: {task.get('status')} · {el:.0f} с")
                if el > 1800:
                    raise GenerationError(f"GPTunneL: задача {task_id} не завершилась за 30 минут")
            if task.get("status") == "failed":
                raise GenerationError(f"GPTunneL: задача {task_id} завершилась ошибкой: "
                                      f"{task.get('error') or task.get('message') or ''}")
            for i, item in enumerate(task.get("result") or []):
                url = item.get("url")
                if not url:
                    continue
                title = safe_name(item.get("title") or req.title or "Suno")
                ext = Path(url.split("?")[0]).suffix.lower() or ".mp3"
                dst = unique_path(out_dir / f"{title}{ext}")
                download(url, dst, cancel=cancel)
                cover = None
                if item.get("cover_url"):
                    try:
                        cext = Path(item["cover_url"].split("?")[0]).suffix or ".jpg"
                        cover = download(item["cover_url"], dst.with_name(dst.stem + "_cover" + cext), cancel=cancel)
                    except requests.RequestException:
                        cover = None
                t = GeneratedTrack(path=dst, title=item.get("title") or title,
                                   lyrics=item.get("lyric") or req.lyrics, cover=cover, engine=self.id,
                                   meta={"model": model_id, "task_id": task_id, "provider_id": item.get("id"),
                                         "tags": item.get("tags"), "duration": item.get("duration"),
                                         "price": task.get("price"), "ignored_params": ignored})
                t.save_sidecar()
                tracks.append(t)
        if not tracks:
            raise GenerationError("GPTunneL вернул задачу без файлов")
        if progress:
            progress(1.0, f"Готово: {len(tracks)} трек(а)")
        return tracks[: max(req.variations, 1) if "suno" not in model_id.lower() else len(tracks)]
