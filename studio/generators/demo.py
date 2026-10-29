"""Демо-движок: процедурный синтез без нейросетей и без сети.

Нужен, чтобы проверить студию «из коробки»: генерирует инструментальный трек с настоящими
раздельными дорожками (ударные, бас, клавиши, лид). Это НЕ AI-генерация и не замена ACE-Step/Suno.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import dsp
from ..audio_io import write_audio
from .base import GeneratedTrack, GenerationRequest, Generator, check_cancel, safe_name, unique_path

SR = 44100
NOTE = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "F": 5, "F#": 6, "GB": 6, "G": 7,
        "G#": 8, "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11}
MAJOR = [0, 2, 4, 5, 7, 9, 11]
MINOR = [0, 2, 3, 5, 7, 8, 10]
PROGRESSIONS = {"major": [[0, 4, 5, 3], [0, 5, 3, 4], [3, 4, 0, 0]],
                "minor": [[0, 5, 2, 6], [0, 3, 4, 4], [0, 6, 5, 4]]}


def parse_key(key: str) -> tuple[int, str]:
    k = (key or "A minor").strip().replace("♯", "#").replace("♭", "b")
    minor = "min" in k.lower() or (len(k) <= 3 and k.endswith("m"))
    root = k.split()[0].rstrip("m") if k else "A"
    root = root[:2].upper() if len(root) > 1 and root[1] in "#bB" else root[:1].upper()
    return NOTE.get(root.upper(), 9), "minor" if minor else "major"


def midi_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def _env(n: int, a: float, d: float, s: float, r: float, sr: int = SR) -> np.ndarray:
    a_n, d_n, r_n = int(a * sr), int(d * sr), int(r * sr)
    s_n = max(0, n - a_n - d_n - r_n)
    e = np.concatenate([np.linspace(0, 1, max(a_n, 1)), np.linspace(1, s, max(d_n, 1)),
                        np.full(s_n, s), np.linspace(s, 0, max(r_n, 1))])
    return np.pad(e, (0, max(0, n - e.size)))[:n]


def _saw(f: float, n: int, rng, detune: float = 0.0) -> np.ndarray:
    t = np.arange(n) / SR
    out = np.zeros(n)
    for dt in (-detune, 0.0, detune) if detune else (0.0,):
        ph = rng.uniform(0, 1)
        out += 2 * ((t * f * (1 + dt) + ph) % 1.0) - 1
    return out / (3 if detune else 1)


def synth_song(req: GenerationRequest) -> tuple[dict, dict]:
    rng = np.random.default_rng(req.seed if req.seed is not None else 7)
    bpm = int(req.bpm or 100)
    beat = 60.0 / bpm
    bar = 4 * beat
    root, mode = parse_key(req.key)
    scale = MINOR if mode == "minor" else MAJOR
    prog = PROGRESSIONS[mode][int(rng.integers(len(PROGRESSIONS[mode])))]
    bars = max(4, int(round(min(req.duration, 240) / bar / 4)) * 4)
    n = int(bars * bar * SR) + SR
    drums, bass, keys, lead = (np.zeros(n) for _ in range(4))
    keys = np.zeros((2, n))

    def put(buf, start_s, sig):
        i = max(0, int(start_s * SR))
        if i >= buf.shape[-1]:
            return
        j = min(buf.shape[-1], i + sig.shape[-1])
        buf[..., i:j] += sig[..., : j - i]

    # ── ударные ──
    kick_n = int(0.35 * SR)
    tk = np.arange(kick_n) / SR
    kick = np.sin(2 * np.pi * (45 * tk + 90 * (1 - np.exp(-tk * 30)) / 30)) * np.exp(-tk * 9)
    snare_n = int(0.25 * SR)
    ts = np.arange(snare_n) / SR
    snare_noise = dsp.apply_eq(rng.standard_normal(snare_n), SR, [("highpass", 900, 0, 0.7)])
    snare = (0.6 * snare_noise * np.exp(-ts * 22) + 0.5 * np.sin(2 * np.pi * 190 * ts) * np.exp(-ts * 30))
    hat_n = int(0.06 * SR)
    hat = dsp.apply_eq(rng.standard_normal(hat_n), SR, [("highpass", 7000, 0, 0.7)]) * np.exp(
        -np.arange(hat_n) / SR * 60)

    for b in range(bars):
        t0 = b * bar
        section = (b // 4) % 4
        for q in range(4):
            if q in (0, 2) or (section >= 2 and q == 3 and b % 2):
                put(drums, t0 + q * beat, kick * 0.9)
            if q in (1, 3) and b >= 2:
                put(drums, t0 + q * beat, snare * 0.7)
            for e in range(2):
                vel = 0.25 if e else 0.35
                put(drums, t0 + q * beat + e * beat / 2 + rng.normal(0, 0.003), hat * vel)

    # ── гармония ──
    for b in range(bars):
        check = prog[b % len(prog)]
        deg = check
        chord = [scale[(deg + i) % 7] + 12 * ((deg + i) // 7) for i in (0, 2, 4)]
        t0 = b * bar
        # бас: восьмые с октавой
        for e in range(8):
            m = 36 + root + chord[0] + (12 if e % 4 == 3 else 0)
            ln = int(beat / 2 * SR * 0.9)
            sig = _saw(midi_hz(m), ln, rng)
            sig = dsp.apply_eq(sig, SR, [("lowpass", 700, 0, 0.9)]) * _env(ln, 0.005, 0.1, 0.6, 0.04)
            put(bass, t0 + e * beat / 2, sig * 0.5)
        # клавиши/пэд: аккорд на такт, лёгкое стерео-расстроение
        ln = int(bar * SR)
        pad = np.zeros((2, ln))
        for i, iv in enumerate(chord):
            f = midi_hz(60 + root + iv)
            pad[0] += _saw(f, ln, rng, detune=0.003)
            pad[1] += _saw(f, ln, rng, detune=0.004)
        pad = dsp.apply_eq(pad, SR, [("lowpass", 2200, 0, 0.7)]) * _env(ln, 0.08, 0.3, 0.7, 0.3) * 0.12
        put(keys, t0, pad)
        # лид: мелодия на пентатонике со второй половины
        if b >= bars // 4:
            penta = [scale[i] for i in (0, 1, 2, 4, 5)]
            for q in range(8):
                if rng.random() < 0.35:
                    continue
                m = 72 + root + penta[int(rng.integers(5))] + (0 if rng.random() < 0.7 else -12)
                dur = beat / 2 * (2 if rng.random() < 0.3 else 1)
                ln2 = int(dur * SR)
                t = np.arange(ln2) / SR
                vib = 1 + 0.004 * np.sin(2 * np.pi * 5.5 * t)
                ph = np.cumsum(2 * np.pi * midi_hz(m) * vib / SR)
                sig = (np.sin(ph) + 0.3 * np.sin(2 * ph) + 0.12 * np.sin(3 * ph)) * _env(ln2, 0.02, 0.1, 0.7, 0.08)
                put(lead, t0 + q * beat / 2, sig * 0.22)

    stems = {"drums": drums, "bass": bass, "keys": keys, "lead": lead}
    for k in stems:
        stems[k] = dsp.fade(stems[k], SR, 0.0, 1.5)
    mix = sum(dsp.to_stereo(dsp.as_2d(v)) for v in stems.values())
    # общий коэффициент для всех дорожек: сумма стемов == микс, без клиппинга ни в одном файле
    g = 0.8 / (np.max(np.abs(mix)) + 1e-9)
    g = min(g, 0.95 / (max(np.max(np.abs(v)) for v in stems.values()) + 1e-9))
    stems = {k: v * g for k, v in stems.items()}
    mix = mix * g
    info = {"bpm": bpm, "key": f"{['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'][root]} {mode}",
            "bars": bars, "progression": prog}
    stems["mix"] = mix
    return stems, info


class DemoGenerator(Generator):
    id = "demo"
    name = "Демо-синтезатор (офлайн, без AI)"
    description = "Процедурный инструментальный трек с раздельными дорожками — для проверки студии без моделей."
    local = True

    def is_available(self) -> tuple[bool, str]:
        return True, "встроен, работает без сети"

    def param_schema(self, model: str = "") -> list[dict]:
        return []

    def generate(self, req: GenerationRequest, out_dir: Path, progress=None, cancel=None) -> list[GeneratedTrack]:
        out_dir = Path(out_dir)
        out = []
        for v in range(max(1, req.variations)):
            check_cancel(cancel)
            r = GenerationRequest(**{**req.__dict__, "seed": (req.seed or 7) + v * 101})
            if progress:
                progress(0.1 + 0.8 * v / max(1, req.variations), f"Демо: синтез варианта {v + 1}")
            stems, info = synth_song(r)
            title = safe_name(req.title or "Демо", "Демо") + (f" — вариант {v + 1}" if req.variations > 1 else "")
            folder = unique_path(out_dir / title)
            folder.mkdir(parents=True, exist_ok=True)
            paths = {}
            for name, a in stems.items():
                if name == "mix":
                    continue
                paths[name] = write_audio(folder / "stems" / f"{name}.wav", a, SR, 24, "wav")
            mix_path = write_audio(folder / f"{title}.wav", stems["mix"], SR, 24, "wav")
            t = GeneratedTrack(path=mix_path, title=title, lyrics="", engine=self.id,
                               meta={**info, "note": "процедурный демо-трек, не AI"}, stems=paths)
            t.save_sidecar()
            out.append(t)
        if progress:
            progress(1.0, f"Готово: {len(out)} трек(а)")
        return out
