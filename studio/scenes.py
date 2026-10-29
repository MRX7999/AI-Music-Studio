"""Акустические сцены: геометрия помещения, ранние отражения, диффузный хвост, эмбиент.

Система координат сцены (метры, вид сверху):
    x — слева направо, 0..width
    y — от задней стены сцены к залу, 0..depth (сцена у y≈0, слушатель дальше)
    z — высота, 0..height
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.signal import sosfilt

from .dsp import apply_eq, biquad, pink_noise

C_SOUND = 343.0
SOURCE_Z = 1.5
PAIR_Z = 2.2


@dataclass
class ScenePreset:
    id: str
    name: str
    width: float
    depth: float
    height: float
    rt60: float
    hf_ratio: float = 0.6        # RT60 на ВЧ относительно середины
    lf_ratio: float = 1.2        # RT60 на НЧ
    early_db: float = 0.0        # масштаб ранних отражений
    stage: tuple = (0.2, 0.05, 0.8, 0.35)   # доли (x0, y0, x1, y1)
    listener: tuple = (0.5, 0.6)            # доли (x, y)
    ambience: str = "none"       # none / roomtone / crowd / outdoor
    ambience_db: float = -60.0   # относительно RMS сухого микса
    description: str = ""
    tags: list = field(default_factory=list)

    @property
    def volume(self) -> float:
        return self.width * self.depth * self.height

    @property
    def surface(self) -> float:
        w, d, h = self.width, self.depth, self.height
        return 2 * (w * d + w * h + d * h)

    def stage_rect(self) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = self.stage
        return x0 * self.width, y0 * self.depth, x1 * self.width, y1 * self.depth

    def listener_pos(self) -> tuple[float, float]:
        return self.listener[0] * self.width, self.listener[1] * self.depth


SCENES: dict[str, ScenePreset] = {s.id: s for s in [
    ScenePreset("dry", "Сухо (без помещения)", 6, 6, 3, 0.0, early_db=-120,
                stage=(0.15, 0.1, 0.85, 0.45), listener=(0.5, 0.75),
                description="Только близкие микрофоны, никакой акустики. Электроника и дальнейшее сведение."),
    ScenePreset("booth", "Вокальная будка", 2.2, 2.0, 2.4, 0.18, hf_ratio=0.5, early_db=-6,
                stage=(0.2, 0.15, 0.8, 0.55), listener=(0.5, 0.8), ambience="roomtone", ambience_db=-58,
                description="Заглушенная будка: интимный близкий вокал, почти без отражений."),
    ScenePreset("studio_a", "Студия A — средняя комната", 9, 7, 3.6, 0.45, hf_ratio=0.7,
                stage=(0.15, 0.1, 0.85, 0.5), listener=(0.5, 0.72), ambience="roomtone", ambience_db=-55,
                description="Сбалансированная студийная комната для записи бэнда целиком."),
    ScenePreset("live_room", "Live room (в духе Abbey Road Studio 2)", 18, 12, 7.5, 1.2, hf_ratio=0.65,
                stage=(0.15, 0.1, 0.85, 0.5), listener=(0.5, 0.7), ambience="roomtone", ambience_db=-52,
                description="Высокий потолок и дерево: «большой» живой звук барабанов и струнных."),
    ScenePreset("garage", "Гараж / репетиционная точка", 6, 5, 2.7, 0.55, hf_ratio=0.95, early_db=3,
                stage=(0.1, 0.1, 0.9, 0.55), listener=(0.5, 0.82), ambience="roomtone", ambience_db=-48,
                description="Бетон и плотные ранние отражения: сырой гаражный рок и панк."),
    ScenePreset("club", "Клуб на 300 человек", 16, 14, 5, 0.9, hf_ratio=0.55,
                stage=(0.25, 0.04, 0.75, 0.25), listener=(0.5, 0.62), ambience="crowd", ambience_db=-30,
                description="Невысокий зал, публика глушит ВЧ, гул толпы между песнями."),
    ScenePreset("concert_hall", "Концертный зал", 40, 30, 16, 2.0, hf_ratio=0.7, lf_ratio=1.25,
                stage=(0.2, 0.03, 0.8, 0.25), listener=(0.5, 0.55), ambience="crowd", ambience_db=-40,
                description="Классический shoebox-зал: обволакивающий хвост ~2 с."),
    ScenePreset("cathedral", "Собор", 28, 70, 30, 4.5, hf_ratio=0.5, lf_ratio=1.3, early_db=-3,
                stage=(0.3, 0.04, 0.7, 0.18), listener=(0.5, 0.4), ambience="roomtone", ambience_db=-50,
                description="Камень и огромный объём: хор, орган, эмбиент. Хвост 4–5 с."),
    ScenePreset("arena", "Арена / стадион", 140, 110, 35, 2.6, hf_ratio=0.45, early_db=-8,
                stage=(0.35, 0.02, 0.65, 0.14), listener=(0.5, 0.45), ambience="crowd", ambience_db=-24,
                description="Огромное пространство, длинные отражения от трибун, шум многотысячной толпы."),
    ScenePreset("open_air", "Open-air / фестиваль", 80, 80, 40, 0.35, hf_ratio=0.4, early_db=-18,
                stage=(0.3, 0.02, 0.7, 0.15), listener=(0.5, 0.4), ambience="outdoor", ambience_db=-32,
                description="Почти без отражений: прямой звук порталов, ветер и толпа под открытым небом."),
]}


# ──────────────────────────────────────────────────────────────
#  Геометрия
# ──────────────────────────────────────────────────────────────

def sabine_reflection(scene: ScenePreset, rt60: float) -> float:
    if rt60 <= 0:
        return 0.0
    alpha = np.clip(0.161 * scene.volume / (rt60 * scene.surface), 0.02, 0.99)
    return float(np.sqrt(1 - alpha))


def critical_distance(scene: ScenePreset, rt60: float) -> float:
    if rt60 <= 0:
        return 1e6
    return float(0.057 * np.sqrt(scene.volume / rt60))


def pair_capsules(lx: float, ly: float, spacing: float = 0.6) -> list[tuple[float, float, float]]:
    """Стереопара A-B из двух omni-капсюлей по оси x."""
    h = spacing / 2
    return [(lx - h, ly, PAIR_Z), (lx + h, ly, PAIR_Z)]


def image_sources(scene: ScenePreset, src: tuple, max_order: int = 2):
    """Мнимые источники прямоугольного помещения: [(x, y, z, order)] без прямого звука."""
    W, D, H = scene.width, scene.depth, scene.height
    xs, ys, zs = src
    out = []
    rng = range(-max_order, max_order + 1)
    for nx in rng:
        for ny in rng:
            for nz in rng:
                order = abs(nx) + abs(ny) + abs(nz)
                if order == 0 or order > max_order:
                    continue
                xi = _img(nx, W, xs)
                yi = _img(ny, D, ys)
                zi = _img(nz, H, zs)
                out.append((xi, yi, zi, order))
    return out


def _img(n: int, L: float, s: float) -> float:
    """Allen & Berkley для одной оси: n отражений → n·L + (s | L − s)."""
    return n * L + (s if n % 2 == 0 else L - s)


def _dist(p: tuple, q: tuple) -> float:
    return float(np.sqrt(sum((a - b) ** 2 for a, b in zip(p, q))))


def spatial_fir(scene: ScenePreset, src_xy: tuple, capsule: tuple, sr: int, rt60: float,
                ref_dist: float, early_scale_db: float = 0.0, align_samples: int = 0,
                max_order: int = 2) -> np.ndarray:
    """FIR прямого звука + ранних отражений для одного капсюля (нормирован на ref_dist)."""
    src = (src_xy[0], src_xy[1], SOURCE_Z)
    taps: list[tuple[float, float]] = []
    d0 = max(_dist(src, capsule), 0.05)
    taps.append((d0 / C_SOUND * sr, ref_dist / d0))
    if rt60 > 0 and scene.early_db > -100:
        refl = sabine_reflection(scene, rt60)
        e_gain = 10 ** ((scene.early_db + early_scale_db) / 20.0)
        for xi, yi, zi, order in image_sources(scene, src, max_order):
            d = _dist((xi, yi, zi), capsule)
            taps.append((d / C_SOUND * sr, (refl ** order) * ref_dist / max(d, 0.05) * e_gain))
    max_delay = max(t for t, _ in taps) - align_samples
    n = int(np.ceil(max(max_delay, 0))) + 2
    fir = np.zeros(n)
    for t, g in taps:
        t = max(t - align_samples, 0.0)
        i = int(t)
        frac = t - i
        if i + 1 < n:
            fir[i] += g * (1 - frac)
            fir[i + 1] += g * frac
    return fir


def direct_delay_samples(src_xy: tuple, capsule: tuple, sr: int) -> float:
    return _dist((src_xy[0], src_xy[1], SOURCE_Z), capsule) / C_SOUND * sr


# ──────────────────────────────────────────────────────────────
#  Диффузный хвост
# ──────────────────────────────────────────────────────────────

def late_tail(scene: ScenePreset, sr: int, rt60: float, seed: int = 0) -> np.ndarray | None:
    """Стерео-хвост единичной энергии с частотно-зависимым затуханием (3 полосы)."""
    if rt60 <= 0.02:
        return None
    rng = np.random.default_rng(seed + 501)
    length = int(sr * min(rt60 * 1.3 + 0.05, 8.0))
    t = np.arange(length) / sr
    t_mix = min(0.002 * np.sqrt(scene.volume) + 0.005, 0.12)
    onset = np.clip((t - 0.25 * t_mix) / max(t_mix, 1e-3), 0, 1) ** 2
    bands = [
        (("lowpass", 400.0), rt60 * scene.lf_ratio),
        (("bandpass", 1600.0), rt60),
        (("highpass", 4500.0), max(rt60 * scene.hf_ratio, 0.05)),
    ]
    out = np.zeros((2, length))
    for (kind, f), band_rt in bands:
        noise = rng.standard_normal((2, length))
        q = 0.5 if kind == "bandpass" else 0.707
        noise = sosfilt(biquad(kind, f, sr, q=q), noise, axis=-1)
        env = np.exp(-6.907755 * t / band_rt)   # −60 дБ за band_rt
        out += noise * env * onset
    # лёгкий спад окна на конце, чтобы не было обрыва
    tail_fade = min(length, int(0.05 * sr))
    out[:, -tail_fade:] *= np.linspace(1, 0, tail_fade)
    energy = np.sqrt(np.sum(np.square(out), axis=1, keepdims=True)) + 1e-12
    return out / energy


# ──────────────────────────────────────────────────────────────
#  Эмбиент помещения
# ──────────────────────────────────────────────────────────────

AMBIENCE_KINDS = {
    "none": "Нет",
    "roomtone": "Тон комнаты",
    "crowd": "Публика",
    "outdoor": "Улица / ветер",
}


def _slow_env(n: int, sr: int, rate_hz: float, rng, depth: float = 1.0) -> np.ndarray:
    k = max(4, int(n / sr * rate_hz) + 4)
    pts = rng.uniform(1 - depth, 1, k)
    return np.interp(np.linspace(0, k - 1, n), np.arange(k), pts)


def ambience(kind: str, n: int, sr: int, seed: int = 0) -> np.ndarray:
    """Стерео-эмбиент с RMS ≈ 1 (уровень задаёт рендер)."""
    if kind == "none" or n <= 0:
        return np.zeros((2, n))
    rng = np.random.default_rng(seed + 900)
    if kind == "roomtone":
        x = pink_noise(n, 2, seed + 901)
        x = apply_eq(x, sr, [("highpass", 35, 0, 0.7), ("lowpass", 2500, 0, 0.7), ("peak", 120, 3, 1.0)])
    elif kind == "crowd":
        voices = np.zeros((2, n))
        for v in range(14):
            nz = rng.standard_normal((2, n))
            f = rng.uniform(350, 1400)
            nz = sosfilt(biquad("bandpass", f, sr, q=1.4), nz, axis=-1)
            syll = _slow_env(n, sr, rng.uniform(3, 6), rng, depth=0.9) ** 2
            phrase = _slow_env(n, sr, rng.uniform(0.2, 0.5), rng, depth=1.0)
            pan = rng.uniform(0.2, 0.8)
            voices[0] += nz[0] * syll * phrase * (1 - pan)
            voices[1] += nz[1] * syll * phrase * pan
        hall = pink_noise(n, 2, seed + 902)
        hall = apply_eq(hall, sr, [("lowpass", 1800, 0, 0.7)])
        x = voices / (np.std(voices) + 1e-12) + 0.5 * hall
    elif kind == "outdoor":
        wind = pink_noise(n, 2, seed + 903)
        wind = apply_eq(wind, sr, [("lowpass", 700, 0, 0.7), ("highpass", 25, 0, 0.7)])
        wind *= _slow_env(n, sr, 0.15, rng, depth=0.8)
        far = ambience("crowd", n, sr, seed + 17)
        far = apply_eq(far, sr, [("lowpass", 2500, 0, 0.7)])
        x = wind + 0.6 * far
    else:
        return np.zeros((2, n))
    return x / (np.sqrt(np.mean(np.square(x))) + 1e-12)
