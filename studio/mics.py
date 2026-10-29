"""Виртуальные микрофоны: АЧХ, диаграмма направленности, эффект близости, собственный шум.

Модели — это обобщённые кривые «в духе» известных классов микрофонов, а не
измеренные профили конкретных экземпляров. Названия брендов использованы только
как ориентир по характеру звучания.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .dsp import apply_eq, saturate

# Полярная диаграмма первого порядка: g(θ) = a + (1 − a)·cos θ
# ree — random energy efficiency: доля диффузного (комнатного) звука относительно omni
PATTERNS = {
    "omni":          dict(name="Круговая (omni)",        a=1.00, ree=1.000),
    "subcardioid":   dict(name="Широкий кардиоид",        a=0.70, ree=0.550),
    "cardioid":      dict(name="Кардиоида",               a=0.50, ree=0.333),
    "supercardioid": dict(name="Суперкардиоида",          a=0.37, ree=0.268),
    "hypercardioid": dict(name="Гиперкардиоида",          a=0.25, ree=0.250),
    "figure8":       dict(name="Восьмёрка",               a=0.00, ree=0.333),
}


@dataclass
class MicModel:
    id: str
    name: str
    kind: str                 # condenser-ld / condenser-sd / dynamic / ribbon / tube / special
    pattern: str
    eq: list = field(default_factory=list)   # [(kind, freq, gain_db, q)]
    proximity: float = 1.0    # множитель эффекта близости (0 — нет)
    offaxis_hf_db: float = -6.0  # потеря ВЧ на 90° вне оси
    self_noise_dba: float = 12.0
    tube_drive_db: float = 0.0
    description: str = ""

    @property
    def pattern_info(self) -> dict:
        return PATTERNS[self.pattern]


MICS: dict[str, MicModel] = {m.id: m for m in [
    MicModel("ldc_tube", "Ламповый LDC (в духе U47)", "tube", "cardioid",
             [("highpass", 30, 0, 0.7), ("peak", 180, 1.5, 0.8), ("peak", 3500, -1.0, 1.2),
              ("peak", 6500, 2.5, 0.9), ("highshelf", 12000, 1.5, 0.7)],
             proximity=1.0, offaxis_hf_db=-7, self_noise_dba=15, tube_drive_db=3.0,
             description="Плотный, тёплый, «дорогой» вокал. Лампа добавляет мягкие гармоники."),
    MicModel("ldc_studio", "Студийный LDC (в духе U87)", "condenser-ld", "cardioid",
             [("highpass", 40, 0, 0.7), ("peak", 4500, 2.5, 0.8), ("peak", 9000, 1.5, 1.0),
              ("highshelf", 14000, -1.0, 0.7)],
             proximity=1.0, offaxis_hf_db=-6, self_noise_dba=12,
             description="Универсальная рабочая лошадка: вокал, акустика, струнные, overhead."),
    MicModel("ldc_bright", "Яркий LDC (в духе C414 / AT4050)", "condenser-ld", "cardioid",
             [("highpass", 40, 0, 0.7), ("peak", 250, -1.0, 0.9), ("peak", 7000, 3.0, 0.9),
              ("highshelf", 11000, 2.5, 0.7)],
             proximity=0.9, offaxis_hf_db=-5, self_noise_dba=11,
             description="Детальный верх, современный «воздушный» поп-вокал, акустическая гитара."),
    MicModel("sdc_pencil", "Малый конденсатор (в духе KM184)", "condenser-sd", "cardioid",
             [("highpass", 50, 0, 0.7), ("peak", 9500, 2.5, 1.2), ("highshelf", 15000, 1.0, 0.7)],
             proximity=0.7, offaxis_hf_db=-3, self_noise_dba=16,
             description="Точная атака: акустика, хэты, overhead, фортепиано."),
    MicModel("dyn_vocal", "Динамический вокальный (в духе SM58)", "dynamic", "cardioid",
             [("highpass", 90, 0, 0.6), ("peak", 200, 1.0, 1.0), ("peak", 4800, 4.0, 1.0),
              ("lowpass", 14500, 0, 0.6)],
             proximity=1.3, offaxis_hf_db=-8, self_noise_dba=0,
             description="Сцена и концерты: плотная середина, ВЧ уходят после 14 кГц."),
    MicModel("dyn_inst", "Динамический инструментальный (в духе SM57)", "dynamic", "cardioid",
             [("highpass", 70, 0, 0.6), ("peak", 6000, 5.0, 1.1), ("peak", 400, -1.0, 1.0),
              ("lowpass", 13500, 0, 0.6)],
             proximity=1.2, offaxis_hf_db=-9, self_noise_dba=0,
             description="Малый барабан и гитарный кабинет: агрессивная атака на 6 кГц."),
    MicModel("dyn_broadcast", "Вещательный динамик (в духе SM7B)", "dynamic", "cardioid",
             [("highpass", 60, 0, 0.6), ("peak", 3000, 1.5, 0.7), ("highshelf", 9000, -1.5, 0.7),
              ("lowpass", 16000, 0, 0.6)],
             proximity=1.1, offaxis_hf_db=-10, self_noise_dba=0,
             description="Ровный, тёмный, мало комнаты. Рок-вокал, подкаст, рэп."),
    MicModel("dyn_kick", "Микрофон бочки (в духе D112 / Beta 52)", "dynamic", "supercardioid",
             [("peak", 60, 4.0, 1.0), ("peak", 400, -6.0, 0.8), ("peak", 4000, 6.0, 1.2),
              ("lowpass", 12000, 0, 0.6)],
             proximity=1.0, offaxis_hf_db=-10, self_noise_dba=0,
             description="Мясо на 60 Гц, вырезанная коробка на 400 Гц и щелчок колотушки."),
    MicModel("ribbon", "Ленточный (в духе R-121 / Coles 4038)", "ribbon", "figure8",
             [("highpass", 25, 0, 0.6), ("peak", 120, 1.0, 0.8), ("highshelf", 8000, -4.0, 0.6)],
             proximity=1.4, offaxis_hf_db=-2, self_noise_dba=18, tube_drive_db=0.0,
             description="Мягкий, винтажный верх. Гитарные кабинеты, духовые, рум-пара."),
    MicModel("omni_measure", "Измерительный omni (в духе DPA 4006)", "condenser-sd", "omni",
             [("highshelf", 12000, 1.0, 0.7)],
             proximity=0.0, offaxis_hf_db=-2, self_noise_dba=15,
             description="Честная АЧХ и много комнаты: классика, акустические ансамбли."),
    MicModel("lofi_phone", "Lo-fi / телефон", "special", "omni",
             [("highpass", 320, 0, 0.9), ("peak", 1800, 4.0, 1.0), ("lowpass", 3400, 0, 0.9)],
             proximity=0.0, offaxis_hf_db=0, self_noise_dba=30, tube_drive_db=6.0,
             description="Узкая полоса 300–3400 Гц, перегруз. Для интро и эффектов."),
    MicModel("di", "DI / линия (без микрофона)", "special", "omni",
             [], proximity=0.0, offaxis_hf_db=0, self_noise_dba=0,
             description="Прямой сигнал без окраски и без комнаты — синтезаторы, бас в линию."),
]}


def polar_gain(pattern: str, angle_deg: float) -> float:
    a = PATTERNS[pattern]["a"]
    # пол −30 дБ: реальные капсюли не дают идеального нуля
    return float(max(abs(a + (1 - a) * np.cos(np.radians(angle_deg))), 0.0316))


def proximity_boost_db(mic: MicModel, distance_m: float) -> float:
    """Подъём НЧ у направленных микрофонов вблизи источника (≈ +10 дБ на 2 см у кардиоиды)."""
    directional = 1.0 - PATTERNS[mic.pattern]["a"]
    if directional <= 0 or mic.proximity <= 0:
        return 0.0
    g = 24.0 * directional * mic.proximity * np.exp(-max(distance_m, 0.005) / 0.12)
    return float(min(g, 16.0))


def color(audio: np.ndarray, sr: int, mic: MicModel, distance_m: float, angle_deg: float,
          seed: int = 0) -> tuple[np.ndarray, dict]:
    """Окрашивает сигнал микрофоном. Возвращает (audio, сводка для UI)."""
    bands = list(mic.eq)
    prox = proximity_boost_db(mic, distance_m)
    if prox > 0.05:
        bands.append(("lowshelf", 160.0, prox, 0.7))
    off = min(abs(angle_deg), 180.0) / 90.0
    hf_loss = mic.offaxis_hf_db * min(off, 1.5)
    if abs(hf_loss) > 0.05:
        bands.append(("highshelf", 6000.0, hf_loss, 0.6))
    out = apply_eq(audio, sr, bands) if bands else audio
    out = out * polar_gain(mic.pattern, angle_deg) if mic.id != "di" else out
    if mic.tube_drive_db > 0:
        out = saturate(out, drive_db=mic.tube_drive_db, even=0.35, mix=0.6)
    if mic.self_noise_dba > 0:
        rng = np.random.default_rng(seed + 11)
        # 94 дБ SPL ≈ −18 dBFS на номинальном уровне → шум = self_noise − 94 − 18
        noise_db = mic.self_noise_dba - 94.0 - 18.0
        out = out + rng.standard_normal(out.shape) * (10 ** (noise_db / 20.0))
    return out, {
        "proximity_db": round(prox, 1),
        "offaxis_hf_db": round(hf_loss, 1),
        "polar_gain_db": round(20 * np.log10(polar_gain(mic.pattern, angle_deg) + 1e-9), 1),
    }
