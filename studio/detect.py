"""Pre-publish AI-music check with independent detectors.

Purpose: know before upload how platform-side detectors are likely to label the track, set the
AI disclosure flags honestly (YouTube `containsSyntheticMedia`, distributor AI credits), and
catch a wrong file (e.g. an unmastered take). It is not a tool for hiding AI origin: the
studio never changes audio based on the verdict.

Detectors
  fakeprint   — built in, offline, no ML framework. Port of lofcz/ai-music-detector (MIT): mean
                dB spectrum 1–8 kHz minus its lower hull, logistic regression (15 KB weights,
                bundled). Method: Afchar et al., "A Fourier Explanation of AI-music Artifacts",
                ISMIR 2025. Trained on Suno ≤ 5 / Udio ≤ 1.5 fakes vs FMA.
  aigm        — local ensemble (SpecTTTra/SONICS on MLX + others) via the `aigm-detector` CLI.
  sightengine — cloud, `type.ai_music` score. Needs a Pro plan for ai_music.
  acrcloud    — cloud, File Scanning container with AI detection enabled (asynchronous).

Each detector returns a score in [0, 1] (probability the audio is AI-generated) or an error;
nothing fails the whole check.
"""
from __future__ import annotations

import json
import os
import time
from math import ceil, gcd
from pathlib import Path

import numpy as np
from scipy.ndimage import minimum_filter1d

from . import tools
from .audio_io import read_audio

MODEL_DIR = Path(__file__).resolve().parent / "models" / "fakeprint"
FP_CFG = {"sample_rate": 16000, "n_fft": 8192, "freq_min": 1000, "freq_max": 8000,
          "hull_area": 10, "max_db": 5, "min_db": -45, "max_seconds": 300}
FP_SHA256 = "d0bc3877a5d575bbe46a97794a72e463fd772258c395a2cbf3d4117aec72a29c"

DETECTORS = {
    "fakeprint": {"label": "Fakeprint (built-in, offline)", "kind": "local",
                  "url": "https://github.com/lofcz/ai-music-detector"},
    "aigm": {"label": "AIGM ensemble: SpecTTTra (MLX) + fakeprint", "kind": "local",
             "url": "https://github.com/shoegazerstella/ai-music-detector"},
    "sightengine": {"label": "Sightengine AI music (cloud)", "kind": "cloud",
                    "url": "https://sightengine.com/docs/ai-generated-music-detection"},
    "acrcloud": {"label": "ACRCloud AI detection (cloud)", "kind": "cloud",
                 "url": "https://docs.acrcloud.com/reference/console-api/file-scanning/metadata/ai-detection"},
}


# ----------------------------------------------------------------- resampling (torchaudio port)

def sinc_resample(x: np.ndarray, orig: int, new: int, lowpass_filter_width: int = 6,
                  rolloff: float = 0.99) -> np.ndarray:
    """Bit-for-bit algorithm of torchaudio.functional.resample (sinc_interp_hann), float32.

    The fakeprint classifier is sensitive to the anti-alias filter shape near 8 kHz, so a
    different resampler (scipy polyphase, soxr) shifts the score."""
    if orig == new:
        return x.astype(np.float32)
    g = gcd(orig, new)
    orig, new = orig // g, new // g
    base_freq = min(orig, new) * rolloff
    width = ceil(lowpass_filter_width * orig / base_freq)
    idx = np.arange(-width, width + orig, dtype=np.float32)[None, :] / orig
    t = np.arange(0, -new, -1, dtype=np.float32)[:, None] / new + idx
    t = t * base_freq
    t = np.clip(t, -lowpass_filter_width, lowpass_filter_width)
    window = np.cos(t * np.pi / lowpass_filter_width / 2) ** 2
    t = t * np.pi
    scale = base_freq / orig
    with np.errstate(invalid="ignore", divide="ignore"):
        k = np.where(t == 0, np.float32(1.0), np.sin(t) / t)
    k = (k * window * scale).astype(np.float32)          # (new, L)
    n = x.shape[-1]
    xp = np.pad(x.astype(np.float32), (width, width + orig))
    L = k.shape[1]
    n_frames = (xp.size - L) // orig + 1
    frames = np.lib.stride_tricks.as_strided(xp, shape=(n_frames, L), strides=(xp.strides[0] * orig, xp.strides[0]))
    out = (frames @ k.T).reshape(-1)
    target = ceil(new * n / orig)
    return out[:target].astype(np.float32)


# ---------------------------------------------------------------------------- fakeprint

_FP = {}


def _fp_weights():
    if not _FP:
        import hashlib
        p = MODEL_DIR / "weights.npz"
        if hashlib.sha256(p.read_bytes()).hexdigest() != FP_SHA256:
            raise RuntimeError("fakeprint weights checksum mismatch")
        d = np.load(p, allow_pickle=False)
        _FP["w"] = d["weights"].reshape(-1).astype(np.float64)
        _FP["b"] = float(d["bias"].reshape(-1)[0])
        freqs = np.linspace(0, FP_CFG["sample_rate"] / 2, num=FP_CFG["n_fft"] // 2 + 1)
        _FP["mask"] = (freqs >= FP_CFG["freq_min"]) & (freqs <= FP_CFG["freq_max"])
    return _FP


def fakeprint_vector(wave16: np.ndarray) -> np.ndarray:
    c = FP_CFG
    x = wave16[: c["max_seconds"] * c["sample_rate"]].astype(np.float32)
    n_fft, hop = c["n_fft"], c["n_fft"] // 2
    pad = n_fft // 2
    if x.size <= pad:
        x = np.pad(x, (0, pad + 1 - x.size))
    xp = np.pad(x, (pad, pad), mode="reflect")
    win = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n_fft) / n_fft)).astype(np.float32)   # periodic hann
    n_frames = 1 + (xp.size - n_fft) // hop
    acc = np.zeros(n_fft // 2 + 1, dtype=np.float64)
    step = 256
    for s in range(0, n_frames, step):
        idx = np.arange(s, min(s + step, n_frames))[:, None] * hop + np.arange(n_fft)[None, :]
        spec = np.abs(np.fft.rfft(xp[idx] * win, axis=1)) ** 2
        acc += (10 * np.log10(np.clip(spec, 1e-10, 1e6))).sum(axis=0)
    mean_db = (acc / n_frames)[_fp_weights()["mask"]]
    hull = minimum_filter1d(mean_db, size=c["hull_area"], mode="nearest")
    hull = np.clip(hull, c["min_db"], None)
    residue = np.clip(mean_db - hull, 0, c["max_db"])
    return (residue / (residue.max() + 1e-6)).astype(np.float32)


def fakeprint_score(audio: np.ndarray, sr: int) -> dict:
    mono = audio.mean(axis=0) if audio.ndim == 2 else audio
    w16 = sinc_resample(mono.astype(np.float32), sr, FP_CFG["sample_rate"])
    fp = fakeprint_vector(w16)
    W = _fp_weights()
    logit = float(fp.astype(np.float64) @ W["w"] + W["b"])
    score = 1.0 / (1.0 + np.exp(-logit))
    return {"score": round(float(score), 4), "logit": round(logit, 4)}


# ------------------------------------------------------------------------------ others

def parse_aigm_output(out: str) -> dict:
    """Result of `aigm-detector predict … --json` from the combined console output.

    aigm-detector 83db9ac prints a few status lines ("Models: …", "Loading …") and then one JSON
    object per file: {"file", "verdict", "ai_probability", "threshold", "backend",
    "model_scores": {name: p}, "models": {name: {"score", "window_scores", …}}, "warnings"}.
    Several files give a JSON list. Older builds used "ensemble_score" / "individual_results"."""
    dec = json.JSONDecoder()
    data = None
    for i, ch in enumerate(out):
        if ch not in "{[":
            continue
        try:
            obj, _ = dec.raw_decode(out, i)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, list):
            obj = next((o for o in obj if isinstance(o, dict)), None)
        if isinstance(obj, dict) and any(k in obj for k in ("ai_probability", "ensemble_score", "score", "model_scores")):
            data = obj
            break
    if data is None:
        tail = [ln.strip() for ln in out.strip().splitlines() if ln.strip()][-1:]
        raise RuntimeError("aigm-detector: no JSON result in the output" + (f" ({tail[0][:200]})" if tail else ""))
    subs: dict[str, float] = {}
    for name, v in (data.get("model_scores") or {}).items():
        if isinstance(v, (int, float)):
            subs[name] = round(float(v), 4)
    for name, v in (data.get("models") or {}).items():
        if isinstance(v, dict) and isinstance(v.get("score"), (int, float)):
            subs.setdefault(name, round(float(v["score"]), 4))
    for r in data.get("individual_results") or data.get("results") or []:
        if isinstance(r, dict) and "model_name" in r and isinstance(r.get("score"), (int, float)):
            subs.setdefault(r["model_name"], round(float(r["score"]), 4))
    score = next((data[k] for k in ("ai_probability", "ensemble_score", "score")
                  if isinstance(data.get(k), (int, float))), None)
    if score is None and subs:
        score = sum(subs.values()) / len(subs)
    if score is None:
        raise RuntimeError("aigm-detector: the result has no ai_probability")
    res = {"score": round(float(score), 4), "models": subs}
    if data.get("verdict"):
        res["verdict"] = str(data["verdict"])
    warnings = [str(w) for w in data.get("warnings") or []]
    if warnings:
        res["warnings"] = warnings
    return res


def _aigm(path: Path, progress=None, cancel=None, models: str = "default") -> dict:
    """`models`: "default" = spectttra-alpha-120s + fakeprint (the ensemble aigm-detector recommends)."""
    backend = "mlx" if tools.is_apple_silicon() else "torch"
    argv = tools.build_argv("aigm", {"input": str(path), "models": models, "backend": backend})
    # wide console: rich must not wrap the status lines or the JSON of a long path
    out = tools.run(argv, progress=progress, cancel=cancel, timeout=1800, label="AIGM",
                    env_extra={"COLUMNS": "1000", "NO_COLOR": "1", "TERM": "dumb"})
    return parse_aigm_output(out)


def _sightengine(path: Path, api_user: str, api_secret: str, session=None) -> dict:
    import requests
    s = session or requests
    with open(path, "rb") as fh:
        r = s.post("https://api.sightengine.com/1.0/audio/check.json",
                   data={"models": "ai_music", "api_user": api_user, "api_secret": api_secret},
                   files={"audio": (path.name, fh)}, timeout=300)
    j = r.json()
    if j.get("status") != "success":
        raise RuntimeError(f"Sightengine: {(j.get('error') or {}).get('message') or j}")
    return {"score": round(float(j["type"]["ai_music"]), 4), "request_id": (j.get("request") or {}).get("id")}


def _find_key(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = _find_key(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_key(v, key)
            if r is not None:
                return r
    return None


def _acrcloud(path: Path, token: str, container_id: str, region: str = "eu-west-1", session=None,
              poll_s: float = 5.0, timeout_s: float = 900, cancel=None) -> dict:
    import requests
    s = session or requests
    base = f"https://api-{region}.acrcloud.com/api/fs-containers/{container_id}/files"
    hdr = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    with open(path, "rb") as fh:
        r = s.post(base, headers=hdr, data={"data_type": "audio"}, files={"file": (path.name, fh)}, timeout=600)
    j = r.json()
    fid = _find_key(j, "id")
    if not fid:
        raise RuntimeError(f"ACRCloud upload failed: {j}")
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if cancel and cancel():
            raise RuntimeError("Cancelled")
        g = s.get(f"{base}/{fid}", headers=hdr, timeout=60).json()
        det = _find_key(g, "ai_detection")
        if det:
            seg = det[0] if isinstance(det, list) else det
            prob = float(seg.get("ai_probability", 0.0))
            return {"score": round(prob / 100.0 if prob > 1 else prob, 4), "file_id": fid,
                    "prediction": seg.get("prediction"), "likely_source": seg.get("likely_source"),
                    "sources": {x.get("source"): x.get("probability") for x in seg.get("source_probabilities") or []}}
        state = _find_key(g, "state")
        if state is not None and int(state) < 0:
            raise RuntimeError(f"ACRCloud processing error (state {state})")
        time.sleep(poll_s)
    raise RuntimeError("ACRCloud: result timeout")


# ------------------------------------------------------------------------------ check

def available(keys: dict | None = None) -> dict:
    keys = keys or {}
    return {
        "fakeprint": True,
        "aigm": bool(tools.find_executable("aigm")),
        "sightengine": bool(keys.get("SIGHTENGINE_API_USER") and keys.get("SIGHTENGINE_API_SECRET")),
        "acrcloud": bool(keys.get("ACRCLOUD_TOKEN") and keys.get("ACRCLOUD_CONTAINER_ID")),
    }


def check(path: str | Path, detectors: list[str] | None = None, keys: dict | None = None,
          threshold: float = 0.5, progress=None, cancel=None, session=None) -> dict:
    """Runs the selected detectors. → report with per-detector results, a summary and the
    disclosure recommendation. `keys` come from Keychain via the app or from env vars."""
    path = Path(path)
    keys = {k: v for k, v in (keys or {}).items() if v}
    for k in ("SIGHTENGINE_API_USER", "SIGHTENGINE_API_SECRET", "ACRCLOUD_TOKEN", "ACRCLOUD_CONTAINER_ID",
              "ACRCLOUD_REGION"):
        keys.setdefault(k, os.environ.get(k, ""))
    avail = available(keys)
    detectors = detectors or [d for d, ok in avail.items() if ok]
    results = {}
    audio = sr = None
    for i, d in enumerate(detectors):
        if cancel and cancel():
            raise RuntimeError("Cancelled")
        if progress:
            progress(0.05 + 0.9 * i / max(len(detectors), 1), f"AI check: {DETECTORS.get(d, {}).get('label', d)}")
        t0 = time.time()
        try:
            if not avail.get(d):
                raise RuntimeError("not configured" if DETECTORS.get(d, {}).get("kind") == "cloud"
                                   else "not installed: " + tools.TOOLS["aigm"].install)
            if d == "fakeprint":
                if audio is None:
                    audio, sr = read_audio(path)
                res = fakeprint_score(audio, sr)
            elif d == "aigm":
                res = _aigm(path, cancel=cancel)
            elif d == "sightengine":
                res = _sightengine(path, keys["SIGHTENGINE_API_USER"], keys["SIGHTENGINE_API_SECRET"], session)
            elif d == "acrcloud":
                res = _acrcloud(path, keys["ACRCLOUD_TOKEN"], keys["ACRCLOUD_CONTAINER_ID"],
                                keys.get("ACRCLOUD_REGION") or "eu-west-1", session, cancel=cancel)
            else:
                raise RuntimeError("unknown detector")
            res["flagged"] = res["score"] >= threshold
            res["ok"] = True
        except Exception as e:  # noqa: BLE001 — one detector must not stop the others
            res = {"ok": False, "error": str(e)}
        res["seconds"] = round(time.time() - t0, 2)
        res["label"] = DETECTORS.get(d, {}).get("label", d)
        results[d] = res
    ok = {d: r for d, r in results.items() if r.get("ok")}
    flagged = [d for d, r in ok.items() if r.get("flagged")]
    mx = max((r["score"] for r in ok.values()), default=None)
    if not ok:
        verdict = "unknown"
    elif len(flagged) == len(ok):
        verdict = "ai"
    elif flagged:
        verdict = "mixed"
    else:
        verdict = "not_detected"
    report = {
        "file": str(path), "time": time.strftime("%Y-%m-%dT%H:%M:%S"), "threshold": threshold,
        "results": results, "verdict": verdict, "max_score": mx, "flagged_by": flagged,
        # an honest default: AI-generated material is disclosed regardless of detector output
        "recommend_disclosure": True,
        "note": ("Detectors disagree or did not flag the track. Platforms still expect disclosure of "
                 "AI-generated or AI-altered music; the publish step sets the flags from the project, "
                 "not from this score.") if verdict != "ai" else
                ("Detectors flag the track as AI-generated. Platforms with similar detectors will very "
                 "likely label it; disclosure flags are set."),
    }
    if progress:
        progress(1.0, f"AI check: {verdict}")
    return report


def save_report(report: dict, out_dir: str | Path) -> Path:
    out = Path(out_dir) / "ai_check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
