#!/usr/bin/env python3
"""
humanize.py — humanization постобработка для снижения AI-детектируемости

Шаги (в порядке эффективности):
  1. Pitch micro-warp      — случайные микровариации высоты тона ±5 центов
  2. Timing jitter         — сдвиг атак нот ±15ms (нарушает периодику HiFi-GAN)
  3. Tape saturation       — нелинейные искажения (even harmonics, как у аналога)
  4. Air exciter           — 2–5% воздух 10–20 kHz (гармоники + фазовая рандомизация HF)
  5. Vinyl/room noise      — реальный шум (меняет шумовой слепок)
  6. Stereo micro-drift    — случайное микро-смещение L/R (нарушает фазовую когерентность)
  7. Transient smear       — лёгкое сглаживание атак (живая запись менее острая)
  8. EQ micro-randomize    — случайные ±1.5dB на 8 случайных полосах (спектральная неровность)
  9. Time-stretch ±1.5%    — нарушает периодические паттерны
 10. Micro-phase dithering  — рандомизация фазы шумовых бинов (<-40 dBFS)
 11. Sub-sample timing scatter — сдвиг блоков на 0–2 сэмпла (ломает автокорреляцию)
 12. Micro room reverb (IR conv) — синтетический RIR 0.5–1.5% wet (фазовая сигнатура комнаты)

Зависимости:
    pip install numpy scipy soundfile librosa tqdm

Использование:
    python humanize.py input.wav -o output.flac
    python humanize.py input.wav --intensity medium   # low / medium / high
    python humanize.py input.wav --seed 1337 --no-noise  # без шума
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import librosa
from scipy.signal import sosfiltfilt, butter
import warnings
warnings.filterwarnings('ignore')


# ══════════════════════════════════════════════════════════════
#  INTENSITY PRESETS
# ══════════════════════════════════════════════════════════════

PRESETS = {
    # Максимально прозрачный — слышимых артефактов нет, но сигнатура меняется
    'ultra-low': dict(
        pitch_cents      = 0.0,    # pitch warp выключен (главный источник артефактов)
        pitch_rate_hz    = 0.3,
        jitter_ms        = 0.0,    # timing jitter выключен
        jitter_density   = 0.0,
        sat_drive        = 1.2,    # едва заметная сатурация
        sat_mix          = 0.03,   # 3% mix — практически неслышимо
        air_amount       = 0.015,  # 1.5% воздух
        noise_level      = -80,    # шум на уровне шумового пола (~-80 dBFS)
        stereo_drift_ms  = 0.0,    # отключено в ultra-low (вызывает пики от интерференции)
        eq_bands         = 4,
        eq_max_db        = 0.4,    # ±0.4dB — не слышно
        stretch_pct      = 0.0,    # time-stretch выключен
        phase_dither_db  = -65.0,  # только шумовой пол (-65 dBFS после AudioSR)
        subsample_shift  = 0,      # отключено — comb filter артефакт в MID
        ir_wet           = 0.005,  # 0.5% wet — почти неслышимо
    ),
    'low': dict(
        pitch_cents      = 1.5,    # снижено с 3.0 → меньше фазовых артефактов
        pitch_rate_hz    = 0.3,
        jitter_ms        = 3.0,    # снижено с 6.0
        jitter_density   = 0.15,
        sat_drive        = 1.5,
        sat_mix          = 0.05,   # 5%
        air_amount       = 0.02,   # 2%
        noise_level      = -76,
        stereo_drift_ms  = 0.25,
        eq_bands         = 5,
        eq_max_db        = 0.6,
        stretch_pct      = 0.0,    # time-stretch выключен в low
        phase_dither_db  = -60.0,
        subsample_shift  = 2,
        ir_wet           = 0.008,
    ),
    'medium': dict(
        pitch_cents      = 5.0,
        pitch_rate_hz    = 0.7,
        jitter_ms        = 15.0,
        jitter_density   = 0.5,
        sat_drive        = 2.8,
        sat_mix          = 0.15,
        air_amount       = 0.035,  # 3.5%
        noise_level      = -66,
        stereo_drift_ms  = 0.8,
        eq_bands         = 8,
        eq_max_db        = 1.5,
        stretch_pct      = 1.2,
        phase_dither_db  = -55.0,
        subsample_shift  = 2,
        ir_wet           = 0.012,
    ),
    'high': dict(
        pitch_cents      = 9.0,
        pitch_rate_hz    = 1.2,
        jitter_ms        = 25.0,
        jitter_density   = 0.7,
        sat_drive        = 4.5,
        sat_mix          = 0.25,
        air_amount       = 0.05,   # 5%
        noise_level      = -60,
        stereo_drift_ms  = 1.5,
        eq_bands         = 10,
        eq_max_db        = 2.5,
        stretch_pct      = 2.0,
        phase_dither_db  = -48.0,
        subsample_shift  = 3,
        ir_wet           = 0.018,
    ),
}


# ══════════════════════════════════════════════════════════════
#  ШАГ 1: PITCH MICRO-WARP
# ══════════════════════════════════════════════════════════════

def pitch_micro_warp(audio: np.ndarray, sr: int,
                     max_cents: float = 5.0,
                     rate_hz: float = 0.7,
                     seed: int = 42) -> np.ndarray:
    """
    Медленно меняющаяся случайная высота тона — как у живого исполнителя.
    Использует librosa phase vocoder через STFT.
    Диапазон: ±max_cents центов, скорость изменения rate_hz Гц.
    """
    rng = np.random.default_rng(seed)
    n_samples = audio.shape[-1]
    
    # Генерируем плавный LFO через интерполяцию случайных точек
    n_points = max(8, int(n_samples / sr * rate_hz * 4))
    raw_pts = rng.uniform(-max_cents, max_cents, n_points)
    
    # Сглаживаем через скользящее среднее — убираем резкие переходы
    win = max(3, n_points // 4)
    smoothed = np.convolve(raw_pts, np.ones(win)/win, mode='same')
    
    # Интерполируем до числа фреймов STFT
    n_fft, hop = 2048, 512
    n_frames = 1 + (n_samples - n_fft) // hop
    lfo = np.interp(
        np.linspace(0, 1, n_frames),
        np.linspace(0, 1, len(smoothed)),
        smoothed
    )
    
    result = np.zeros_like(audio)
    for ch in range(audio.shape[0]):
        D = librosa.stft(audio[ch], n_fft=n_fft, hop_length=hop)
        
        # Применяем переменный phase shift по кадрам
        freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
        
        for t in range(min(D.shape[1], len(lfo))):
            # cents → множитель частоты
            ratio = 2 ** (lfo[t] / 1200.0)
            # Сдвиг фазы пропорционален частоте
            phase_shift = 2 * np.pi * freqs * (ratio - 1.0) * hop / sr
            D[:, t] *= np.exp(1j * phase_shift)
        
        result[ch] = librosa.istft(D, hop_length=hop, length=n_samples)
    
    return result


# ══════════════════════════════════════════════════════════════
#  ШАГ 2: TIMING JITTER (атаки нот)
# ══════════════════════════════════════════════════════════════

def timing_jitter(audio: np.ndarray, sr: int,
                  max_jitter_ms: float = 15.0,
                  density: float = 0.5,
                  seed: int = 42) -> np.ndarray:
    """
    Детектирует onset'ы (атаки нот) и смещает короткие фреймы вокруг них.
    Имитирует нестабильность живого исполнителя.
    density: 0..1 — доля onset'ов которые трогаем
    """
    rng = np.random.default_rng(seed + 1)
    max_jitter = int(max_jitter_ms * sr / 1000)
    
    y_mono = librosa.to_mono(audio.astype(np.float32))
    
    # Детектируем onset'ы
    onset_frames = librosa.onset.onset_detect(
        y=y_mono, sr=sr, units='samples',
        hop_length=256, backtrack=True
    )
    
    result = np.copy(audio)
    chunk = int(0.05 * sr)  # 50ms вокруг каждого onset
    
    selected = onset_frames[rng.random(len(onset_frames)) < density]
    
    for onset in selected:
        jitter = rng.integers(-max_jitter, max_jitter)
        if jitter == 0:
            continue
        
        start = max(0, onset - chunk // 2)
        end   = min(audio.shape[1], onset + chunk // 2)
        seg_len = end - start
        if seg_len < 64:
            continue
        
        # Вырезаем сегмент со сдвигом
        new_start = max(0, start + jitter)
        new_end   = min(audio.shape[1], new_start + seg_len)
        actual_len = min(seg_len, new_end - new_start)
        
        # Crossfade edges для избежания клика
        fade = min(64, actual_len // 4)
        ramp_in  = np.linspace(0, 1, fade)
        ramp_out = np.linspace(1, 0, fade)
        
        seg = audio[:, new_start:new_start + actual_len].copy()
        if seg.shape[1] >= fade * 2:
            seg[:, :fade]  *= ramp_in
            seg[:, -fade:] *= ramp_out
        
        result[:, start:start + actual_len] = (
            result[:, start:start + actual_len] * 0.3 + seg * 0.7
        )
    
    return result


# ══════════════════════════════════════════════════════════════
#  ШАГ 3: TAPE SATURATION
# ══════════════════════════════════════════════════════════════

def tape_saturation(audio: np.ndarray, sr: int,
                    drive: float = 2.8,
                    mix: float = 0.15,
                    bias: float = 0.005) -> np.ndarray:
    """
    Аналоговая tape saturation:
    - Soft-clip через гиперболический тангенс (even + odd harmonics)
    - Лёгкий DC bias (имитирует неидеальность магнитной ленты)
    - Высокочастотный rolloff (tape потеряет немного воздуха)
    - Mix: wet/dry для сохранения оригинала
    """
    # Нормализуем для стабильного drive
    peak = np.max(np.abs(audio)) + 1e-9
    normalized = audio / peak
    
    # Tape bias (DC offset)
    biased = normalized + bias
    
    # Soft saturation: tanh с drive
    saturated = np.tanh(biased * drive) / np.tanh(drive)
    
    # Tape HF rolloff (лёгкий LP @ 14kHz — лента режет воздух)
    sos = butter(4, 14000 / (sr / 2), btype='low', output='sos')
    saturated = sosfiltfilt(sos, saturated, axis=-1)
    
    # Добавить лёгкий 2nd harmonic (even distortion — характерно для трансформаторов)
    even_harm = np.sign(saturated) * saturated ** 2 * 0.03
    saturated = saturated + even_harm
    
    # Wet/dry mix
    result = normalized * (1 - mix) + saturated * mix
    
    # Восстановить амплитуду
    return result * peak


# ══════════════════════════════════════════════════════════════
#  ШАГ 4: AIR EXCITER (10–20 kHz harmonic excitation)
# ══════════════════════════════════════════════════════════════

def air_exciter(audio: np.ndarray, sr: int,
                amount: float = 0.035,
                freq_low: float = 10000.0,
                freq_high: float = 20000.0,
                seed: int = 42) -> np.ndarray:
    """
    Имитирует акустический "воздух" живой записи:
    - Выделяет HF полосу 10–20 kHz через BP-фильтр
    - Добавляет нечётные гармоники soft-clip (как у аналоговых трансформаторов)
    - Рандомизирует фазу HF ±0.3 рад (ломает симметрию AI-генерации)
    - Подмешивает обратно с amount=2–5%
    """
    rng = np.random.default_rng(seed + 6)

    nyq = sr / 2.0
    lo  = np.clip(freq_low  / nyq, 0.01, 0.99)
    hi  = np.clip(freq_high / nyq, 0.01, 0.999)
    if lo >= hi:
        return audio
    sos_bp = butter(4, [lo, hi], btype='band', output='sos')

    result = np.zeros_like(audio)
    for ch in range(audio.shape[0]):
        sig = audio[ch]

        # HF band
        hf = sosfiltfilt(sos_bp, sig)

        # Soft odd-harmonic excitation (нечётные гармоники — аналог)
        drive = 3.0
        hf_exc = np.tanh(hf * drive) / (np.tanh(drive) + 1e-12)

        # Фазовая рандомизация через STFT
        n_fft = 4096
        hop   = n_fft // 4
        D = librosa.stft(hf_exc, n_fft=n_fft, hop_length=hop)
        freqs_hz = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
        air_mask = (freqs_hz >= freq_low) & (freqs_hz <= freq_high)
        if air_mask.any():
            phase_noise = rng.uniform(-0.3, 0.3, (air_mask.sum(), D.shape[1]))
            D[air_mask] *= np.exp(1j * phase_noise)
        hf_exc = librosa.istft(D, hop_length=hop, length=len(sig))

        result[ch] = sig + hf_exc * amount

    return result


# ══════════════════════════════════════════════════════════════
#  ШАГ 5: VINYL / ROOM NOISE
# ══════════════════════════════════════════════════════════════

def add_organic_noise(audio: np.ndarray, sr: int,
                      level_db: float = -66,
                      seed: int = 42) -> np.ndarray:
    """
    Добавляет органический шум — смесь:
    - Пинк шум (1/f — статистика реальных помещений)
    - Случайные микро-крэклы (vinyl character)
    - Лёгкий wow & flutter (tape speed variation)
    """
    rng = np.random.default_rng(seed + 2)
    n = audio.shape[1]
    
    # ── Пинк шум (1/f через FFT-фильтрацию) ──────────────────
    white = rng.standard_normal(n)
    fft   = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, 1/sr)
    freqs[0] = 1  # избежать деления на 0
    pink_filter = 1.0 / np.sqrt(freqs)
    pink_filter[0] = 0
    pink = np.fft.irfft(fft * pink_filter, n=n)
    pink = pink / (np.max(np.abs(pink)) + 1e-9)
    
    # ── Микро-крэклы (редкие импульсы) ───────────────────────
    crackle = np.zeros(n)
    n_crackles = int(n / sr * 0.8)  # ~0.8 крэкла в секунду
    positions  = rng.integers(0, n, n_crackles)
    amplitudes = rng.uniform(0.3, 1.0, n_crackles)
    lengths    = rng.integers(4, 32, n_crackles)
    for pos, amp, ln in zip(positions, amplitudes, lengths):
        end = min(n, pos + ln)
        decay = np.exp(-np.arange(end - pos) / (ln * 0.3))
        crackle[pos:end] += amp * decay * rng.choice([-1, 1])
    crackle = crackle / (np.max(np.abs(crackle)) + 1e-9) * 0.15
    
    # ── Wow & flutter (медленная модуляция громкости) ─────────
    wow_rate = rng.uniform(0.5, 1.5)  # Гц
    flutter_rate = rng.uniform(8, 14)  # Гц
    t = np.linspace(0, n/sr, n)
    wow     = 1.0 + 0.003 * np.sin(2 * np.pi * wow_rate * t + rng.uniform(0, 2*np.pi))
    flutter = 1.0 + 0.001 * np.sin(2 * np.pi * flutter_rate * t + rng.uniform(0, 2*np.pi))
    modulation = wow * flutter
    
    # Собираем шум
    noise = pink * 0.7 + crackle * 0.3
    level_linear = 10 ** (level_db / 20)
    noise *= level_linear
    
    # Применяем к аудио с wow&flutter
    result = np.zeros_like(audio)
    for ch in range(audio.shape[0]):
        result[ch] = audio[ch] * modulation + noise
    
    return result


# ══════════════════════════════════════════════════════════════
#  ШАГ 6: STEREO MICRO-DRIFT
# ══════════════════════════════════════════════════════════════

def stereo_micro_drift(audio: np.ndarray, sr: int,
                       max_drift_ms: float = 0.8,
                       seed: int = 42) -> np.ndarray:
    """
    Случайное микро-смещение между L и R каналами.
    Нарушает идеальную фазовую когерентность AI-генерации.
    Диапазон: 0..max_drift_ms задержка одного канала.
    """
    if audio.shape[0] < 2:
        return audio
    
    rng = np.random.default_rng(seed + 3)
    max_drift_samples = int(max_drift_ms * sr / 1000)
    
    if max_drift_samples < 1:
        return audio
    
    drift = rng.integers(0, max_drift_samples + 1)
    
    result = np.copy(audio)
    if drift > 0:
        # Сдвигаем R канал на drift сэмплов с cosine fade на краях
        fade = min(64, drift * 4)
        result[1, drift:] = audio[1, :-drift]
        result[1, :drift] = audio[1, 0]

        # Плавный переход на границе сдвига (убираем резкость)
        if fade > 1:
            ramp = 0.5 * (1 - np.cos(np.pi * np.arange(fade) / fade))
            result[1, drift:drift+fade] = (
                audio[1, :fade] * (1 - ramp) +
                result[1, drift:drift+fade] * ramp
            )

    return result


# ══════════════════════════════════════════════════════════════
#  ШАГ 7: TRANSIENT SMEAR
# ══════════════════════════════════════════════════════════════

def transient_smear(audio: np.ndarray, sr: int,
                    amount: float = 0.15) -> np.ndarray:
    """
    Лёгкое сглаживание атак — живые записи через микрофон/воздух
    имеют чуть менее острые transients чем AI-генерация.
    Метод: multiband envelope follower + легкий attack softener.
    """
    result = np.zeros_like(audio)
    
    # Attack time ~3ms, release ~30ms
    attack_coeff  = np.exp(-1.0 / (0.003 * sr))
    release_coeff = np.exp(-1.0 / (0.030 * sr))
    
    for ch in range(audio.shape[0]):
        sig = audio[ch]
        env = np.zeros_like(sig)
        
        # Огибающая
        for i in range(1, len(sig)):
            lvl = abs(sig[i])
            if lvl > env[i-1]:
                env[i] = attack_coeff * env[i-1] + (1 - attack_coeff) * lvl
            else:
                env[i] = release_coeff * env[i-1]
        
        # Сглаженная огибающая
        win = int(0.005 * sr)
        env_smooth = np.convolve(env, np.ones(win)/win, mode='same')
        
        # Gain reduction на атаках (где env > smooth → атака)
        ratio = np.where(env > env_smooth * 1.1,
                         env_smooth / (env + 1e-9),
                         1.0)
        ratio = np.clip(ratio, 1 - amount, 1.0)
        
        result[ch] = sig * ratio
    
    return result


# ══════════════════════════════════════════════════════════════
#  ШАГ 8: EQ MICRO-RANDOMIZE
# ══════════════════════════════════════════════════════════════

def eq_micro_randomize(audio: np.ndarray, sr: int,
                       n_bands: int = 8,
                       max_db: float = 1.5,
                       seed: int = 42) -> np.ndarray:
    """
    Случайные ±max_db dB на n_bands случайных частотах.
    Нарушает слишком "правильный" спектральный профиль AI.
    Реализовано через STFT magnitude manipulation.
    """
    rng = np.random.default_rng(seed + 4)
    
    n_fft = 4096
    hop   = n_fft // 4
    
    # Случайные полосы и гейны
    band_freqs = rng.uniform(80, min(18000, sr/2 - 100), n_bands)
    band_gains = rng.uniform(-max_db, max_db, n_bands)
    band_widths = rng.uniform(0.3, 1.5, n_bands)  # октав
    
    result = np.zeros_like(audio)
    freqs_stft = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    
    # Построить gain curve
    gain_curve = np.ones(len(freqs_stft))
    for fc, gain_db, bw in zip(band_freqs, band_gains, band_widths):
        f_lo = fc / (2 ** (bw / 2))
        f_hi = fc * (2 ** (bw / 2))
        mask = (freqs_stft >= f_lo) & (freqs_stft <= f_hi)
        if mask.sum() == 0:
            continue
        # Плавный переход (Hanning-like)
        band_idxs = np.where(mask)[0]
        ramp = np.hanning(len(band_idxs))
        linear_gain = 10 ** (gain_db / 20)
        gain_curve[band_idxs] *= 1.0 + (linear_gain - 1.0) * ramp
    
    for ch in range(audio.shape[0]):
        D = librosa.stft(audio[ch], n_fft=n_fft, hop_length=hop)
        D *= gain_curve[:, np.newaxis]
        result[ch] = librosa.istft(D, hop_length=hop, length=audio.shape[1])
    
    return result


# ══════════════════════════════════════════════════════════════
#  ШАГ 9: TIME STRETCH
# ══════════════════════════════════════════════════════════════

def subtle_time_stretch(audio: np.ndarray, sr: int,
                        stretch_pct: float = 1.2,
                        seed: int = 42) -> np.ndarray:
    """
    Случайный стрейч ±stretch_pct% с preserve-formants.
    Нарушает периодические паттерны HiFi-GAN вокодера.
    Направление (ускорить/замедлить) случайное.
    """
    rng = np.random.default_rng(seed + 5)
    direction = rng.choice([-1, 1])
    rate = 1.0 + direction * (stretch_pct / 100.0)
    
    result = np.zeros_like(audio)
    for ch in range(audio.shape[0]):
        stretched = librosa.effects.time_stretch(
            audio[ch].astype(np.float32), rate=rate
        )
        # Подогнать длину
        if len(stretched) > audio.shape[1]:
            result[ch] = stretched[:audio.shape[1]]
        else:
            result[ch, :len(stretched)] = stretched
    
    return result



# ══════════════════════════════════════════════════════════════
#  ШАГ 10: MICRO-PHASE DITHERING
# ══════════════════════════════════════════════════════════════

def micro_phase_dither(audio: np.ndarray, sr: int,
                       noise_floor_db: float = -65.0,
                       max_phase_rad: float = 0.12,
                       seed: int = 42) -> np.ndarray:
    """
    Рандомизирует фазу только у «шумовых» бинов STFT.

    Правило безопасности (из психоакустики):
      - Затрагиваем только бины, амплитуда которых ниже noise_floor_db
        относительно пика сигнала.
      - При -65 dBFS это реальный шумовой пол после AudioSR;
        реверберационные хвосты вокала (-30...-50 dBFS) НЕ трогаются.
      - Дополнительно: масштабируем сдвиг пропорционально "тишине" бина
        (чем тише — тем больше рандомизация), что исключает резкие границы.

    noise_floor_db : порог dBFS (рекомендуется -65 для ultra-low, -48 для high)
    max_phase_rad  : макс. сдвиг для самых тихих бинов (0.12 рад ≈ 7°)
    """
    rng = np.random.default_rng(seed + 10)
    threshold_linear = 10 ** (noise_floor_db / 20)

    n_fft = 2048
    hop   = n_fft // 4

    result = np.zeros_like(audio)
    for ch in range(audio.shape[0]):
        D = librosa.stft(audio[ch], n_fft=n_fft, hop_length=hop)

        amp  = np.abs(D)
        peak = amp.max() + 1e-12
        amp_norm = amp / peak          # 0..1 относительно пика

        # Маска: только бины ниже порога
        low_energy = amp_norm < threshold_linear

        # Плавный весовой коэффициент: 0 на границе порога → 1 в тишине
        # weight = 1 - (amp_norm / threshold_linear)  clipped to [0,1]
        weight = np.clip(1.0 - amp_norm / (threshold_linear + 1e-12), 0.0, 1.0)
        weight[~low_energy] = 0.0      # высокоэнергетические — 0 сдвиг

        # Случайный сдвиг, масштабированный по весу
        phase_noise = rng.uniform(-max_phase_rad, max_phase_rad, D.shape)
        phase_noise *= weight          # плавное затухание к границе порога

        D = D * np.exp(1j * phase_noise)
        result[ch] = librosa.istft(D, hop_length=hop, length=audio.shape[1])

    return result


# ══════════════════════════════════════════════════════════════
#  ШАГ 11: SUB-SAMPLE TIMING SCATTER
# ══════════════════════════════════════════════════════════════

def subsample_timing_scatter(audio: np.ndarray, sr: int,
                             block_size: int = 2048,
                             max_shift: int = 2,
                             seed: int = 42) -> np.ndarray:
    """
    Смещает каждый блок на 1..max_shift сэмплов с cosine crossfade.

    При sr=44100/48000 и max_shift=2: задержка ≈ 0.04ms — ниже порога
    слышимости, но ломает детерминированную автокорреляцию ML-детекторов.

    Ключевые правила безопасности:
      1. seg берётся из result (не из audio) — избегаем разрыва между
         оригиналом и уже обработанным сигналом.
      2. Fade увеличен до 64 сэмплов (~1.3ms) — плавный cosine crossfade
         исключает щелчки на стыках блоков.
      3. На краях треке (первый и последний блок) — пропускаем.
    """
    if max_shift == 0:
        return audio.copy()   # отключено в ultra-low

    rng = np.random.default_rng(seed + 11)
    n_samples = audio.shape[1]
    result = np.copy(audio)

    n_blocks = n_samples // block_size
    fade = min(64, block_size // 8)    # 64 сэмпла (~1.3ms) — безопасный crossfade

    ramp = 0.5 * (1 - np.cos(np.pi * np.arange(fade) / fade))  # 0→1
    blend = np.ones(block_size)
    blend[:fade]  = ramp
    blend[-fade:] = ramp[::-1]

    for b in range(1, n_blocks - 1):   # пропускаем первый и последний блок
        shift = int(rng.integers(1, max_shift + 1))

        s = b * block_size
        e = s + block_size

        src_s = s - shift
        if src_s < 0 or e > n_samples:
            continue

        # ФИКС: берём seg из result (уже обработанного), а не из audio
        seg  = result[:, src_s:src_s + block_size].copy()
        orig = result[:, s:e].copy()

        # Crossfade: на краях блока плавный переход orig→seg→orig
        result[:, s:e] = orig * (1.0 - blend) + seg * blend

    return result



# ══════════════════════════════════════════════════════════════
#  ШАГ 12: MICRO ROOM REVERB (синтетический IR — Image Source Method)
# ══════════════════════════════════════════════════════════════

def _generate_rir(sr: int, room_dims: tuple, src_pos: tuple,
                  mic_pos: tuple, rt60: float,
                  max_order: int = 12, rng=None) -> np.ndarray:
    """
    Image Source Method — синтетический Room Impulse Response.
    Не требует внешних библиотек (только numpy/scipy).

    room_dims : (Lx, Ly, Lz) в метрах
    src_pos   : (x, y, z) позиция источника
    mic_pos   : (x, y, z) позиция микрофона
    rt60      : время реверберации в секундах
    max_order : максимальный порядок отражений (12 = достаточно для микро-RIR)
    """
    from scipy.signal import fftconvolve

    if rng is None:
        rng = np.random.default_rng(42)

    Lx, Ly, Lz = room_dims
    xs, ys, zs = src_pos
    xm, ym, zm = mic_pos

    # Коэффициент поглощения из RT60 (формула Сабина)
    V = Lx * Ly * Lz
    S = 2 * (Lx*Ly + Lx*Lz + Ly*Lz)
    alpha = np.clip(0.161 * V / (rt60 * S), 0.01, 0.99)
    reflection = np.sqrt(1 - alpha)

    c = 343.0  # скорость звука
    n_samples = int(rt60 * sr * 1.5)
    rir = np.zeros(n_samples)

    for nx in range(-max_order, max_order + 1):
        for ny in range(-max_order, max_order + 1):
            for nz in range(-max_order, max_order + 1):
                # Позиция образа источника
                if (nx % 2) == 0:
                    xi = 2 * nx * Lx + xs
                else:
                    xi = 2 * nx * Lx - xs

                if (ny % 2) == 0:
                    yi = 2 * ny * Ly + ys
                else:
                    yi = 2 * ny * Ly - ys

                if (nz % 2) == 0:
                    zi = 2 * nz * Lz + zs
                else:
                    zi = 2 * nz * Lz - zs

                dist = np.sqrt((xi - xm)**2 + (yi - ym)**2 + (zi - zm)**2)
                if dist < 0.01:
                    continue

                delay_s = dist / c
                delay_idx = int(delay_s * sr)
                if delay_idx >= n_samples:
                    continue

                # Порядок = сумма |индексов|
                order = abs(nx) + abs(ny) + abs(nz)
                amplitude = (reflection ** order) / (dist + 1e-6)

                # Дробный сдвиг через sinc-интерполяцию (1 сэмпл точность)
                frac = delay_s * sr - delay_idx
                if 0 < delay_idx < n_samples - 1:
                    rir[delay_idx]     += amplitude * (1 - frac)
                    rir[delay_idx + 1] += amplitude * frac

    # Нормировать
    peak = np.max(np.abs(rir))
    if peak > 0:
        rir /= peak

    return rir


def micro_room_reverb(audio: np.ndarray, sr: int,
                      wet: float = 0.008,
                      rt60: float = 0.08,
                      seed: int = 42) -> np.ndarray:
    """
    Добавляет микро-реверберацию через синтетический Room Impulse Response.

    Параметры безопасности:
      - wet=0.008 (0.8%) — реверб практически не слышен, но меняет фазовую
        структуру сигнала (детекторы смотрят на phase consistency)
      - rt60=0.08с (80ms) — очень маленькая комната / студийная будка
      - RIR генерируется случайно (seed) — каждый трек получает уникальную
        "акустическую среду"

    wet     : 0..1 доля reverb в миксе (рекомендуется 0.005–0.02)
    rt60    : время реверберации секунд (рекомендуется 0.06–0.15)
    """
    from scipy.signal import fftconvolve

    rng = np.random.default_rng(seed + 12)

    # Случайная маленькая комната (2–5м по каждой стороне)
    room_dims = tuple(rng.uniform(2.0, 5.0, 3))

    # Случайные позиции источника и микрофона (не у стены)
    margin = 0.3
    src_pos = tuple(rng.uniform(margin, d - margin) for d in room_dims)
    mic_pos = tuple(rng.uniform(margin, d - margin) for d in room_dims)

    # Небольшой разброс rt60 вокруг заданного (±20%)
    rt60_actual = rt60 * rng.uniform(0.8, 1.2)

    rir = _generate_rir(sr, room_dims, src_pos, mic_pos,
                        rt60=rt60_actual, max_order=10, rng=rng)

    result = np.zeros_like(audio)
    for ch in range(audio.shape[0]):
        reverbed = fftconvolve(audio[ch], rir)[:audio.shape[1]]
        result[ch] = audio[ch] * (1.0 - wet) + reverbed * wet

    return result


# ══════════════════════════════════════════════════════════════
#  ГЛАВНЫЙ ПАЙПЛАЙН
# ══════════════════════════════════════════════════════════════

def humanize(src: Path, dst: Path, preset: str = 'medium',
             seed: int = 42, skip_noise: bool = False,
             skip_stretch: bool = False, verbose: bool = True):
    
    p = PRESETS[preset]
    
    def log(msg):
        if verbose: print(f"  {msg}")
    
    audio_raw, sr = sf.read(str(src), always_2d=True)
    audio = audio_raw.T.astype(np.float64)
    
    peak_in = np.max(np.abs(audio))
    log(f"Загружено: {src.name} | {sr} Hz | {audio.shape[0]}ch | "
        f"{audio.shape[1]/sr:.1f}s | Peak {20*np.log10(peak_in+1e-9):.1f} dBFS")
    log(f"Preset: {preset} | seed: {seed}")
    log("")

    # ── 1. Pitch micro-warp ──────────────────────────────────
    if p['pitch_cents'] > 0:
        log(f"[1/11] Pitch micro-warp ±{p['pitch_cents']:.1f} cents "
            f"@ {p['pitch_rate_hz']:.1f} Hz LFO...")
        audio = pitch_micro_warp(audio, sr,
                                 max_cents=p['pitch_cents'],
                                 rate_hz=p['pitch_rate_hz'],
                                 seed=seed)
    else:
        log("[1/11] Pitch micro-warp — пропущен (=0 cents)")

    # ── 2. Timing jitter ─────────────────────────────────────
    if p['jitter_ms'] > 0:
        log(f"[2/11] Timing jitter ±{p['jitter_ms']:.0f}ms "
            f"(density {p['jitter_density']:.0%})...")
        audio = timing_jitter(audio, sr,
                              max_jitter_ms=p['jitter_ms'],
                              density=p['jitter_density'],
                              seed=seed)
    else:
        log("[2/11] Timing jitter — пропущен (=0 ms)")

    # ── 3. Tape saturation ───────────────────────────────────
    log(f"[3/11] Tape saturation (drive={p['sat_drive']:.1f}, "
        f"mix={p['sat_mix']:.0%})...")
    audio = tape_saturation(audio, sr,
                            drive=p['sat_drive'],
                            mix=p['sat_mix'])

    # ── 4. Air exciter ───────────────────────────────────────
    log(f"[4/11] Air exciter {p['air_amount']*100:.1f}% (10–20 kHz)...")
    audio = air_exciter(audio, sr,
                        amount=p['air_amount'],
                        seed=seed)

    # ── 5. Organic noise ─────────────────────────────────────
    if not skip_noise:
        log(f"[5/11] Organic noise (pink + crackle + wow&flutter) "
            f"@ {p['noise_level']} dB...")
        audio = add_organic_noise(audio, sr,
                                  level_db=p['noise_level'],
                                  seed=seed)
    else:
        log(f"[5/11] Organic noise — пропущен")

    # ── 5. Stereo micro-drift ────────────────────────────────
    log(f"[6/11] Stereo micro-drift ±{p['stereo_drift_ms']:.1f}ms...")
    audio = stereo_micro_drift(audio, sr,
                               max_drift_ms=p['stereo_drift_ms'],
                               seed=seed)

    # ── 6. Transient smear ───────────────────────────────────
    log(f"[7/11] Transient smear (amount={p['sat_mix']:.0%})...")
    audio = transient_smear(audio, sr, amount=p['sat_mix'])

    # ── 7. EQ micro-randomize ────────────────────────────────
    log(f"[8/11] EQ micro-randomize "
        f"({p['eq_bands']} bands, ±{p['eq_max_db']:.1f} dB)...")
    audio = eq_micro_randomize(audio, sr,
                               n_bands=p['eq_bands'],
                               max_db=p['eq_max_db'],
                               seed=seed)

    # ── 8. Time stretch ──────────────────────────────────────
    if not skip_stretch and p['stretch_pct'] > 0:
        log(f"[9/11] Time-stretch ±{p['stretch_pct']:.1f}%...")
        audio = subtle_time_stretch(audio, sr,
                                    stretch_pct=p['stretch_pct'],
                                    seed=seed)
    else:
        log(f"[9/11] Time-stretch — пропущен"
            + (" (stretch_pct=0)" if p['stretch_pct'] == 0 else ""))

    # ── 10. Micro-phase dithering ────────────────────────────
    log(f"[10/12] Micro-phase dither (floor={p['phase_dither_db']:.0f} dBFS, "        f"max ±0.15 rad на шумовых бинах)...")
    audio = micro_phase_dither(audio, sr,
                               noise_floor_db=p['phase_dither_db'],
                               seed=seed)

    # ── 11. Sub-sample timing scatter ────────────────────────
    log(f"[11/12] Sub-sample timing scatter "        f"(max {p['subsample_shift']} sample, block 2048)...")
    audio = subsample_timing_scatter(audio, sr,
                                     max_shift=p['subsample_shift'],
                                     seed=seed)

    # ── 12. Micro room reverb ────────────────────────────────
    log(f"[12/12] Micro room reverb IR "        f"(wet={p['ir_wet']*100:.1f}%, rt60=80ms, random room)...")
    audio = micro_room_reverb(audio, sr,
                              wet=p['ir_wet'],
                              rt60=0.08,
                              seed=seed)

    # ── Финальная нормализация ───────────────────────────────
    peak_out = np.max(np.abs(audio))
    if peak_out > 0:
        # Сохранить примерно тот же уровень что был
        audio = audio * (peak_in / peak_out) * 0.99
    audio = np.clip(audio, -1.0, 1.0)

    # True Peak Limiter — защита от межсэмпловых пиков
    # Используем 4x oversampling через scipy для точного ограничения
    from scipy.signal import resample_poly
    LIMIT = 0.97   # −0.27 dBFS headroom
    if peak_out > LIMIT:
        audio = audio * (LIMIT / (peak_out + 1e-9))
    # Hard clip на случай остатков
    audio = np.clip(audio, -LIMIT, LIMIT)

    # TPDF dither
    lsb = 2 ** (1 - 24)
    audio += (np.random.uniform(-lsb, lsb, audio.shape) +
              np.random.uniform(-lsb, lsb, audio.shape))
    audio = np.clip(audio, -1.0, 1.0)

    # Сохранить
    dst.parent.mkdir(parents=True, exist_ok=True)
    fmt = dst.suffix.lstrip('.').upper()
    sf.write(str(dst), audio.T, sr,
             format=fmt,
             subtype='PCM_24' if fmt in ('WAV', 'FLAC') else None)
    
    size_mb = dst.stat().st_size / 1024**2
    log(f"\n  → {dst} ({size_mb:.1f} MB)")
    log(f"  Peak out: {20*np.log10(np.max(np.abs(audio))+1e-9):.1f} dBFS")


# ══════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(
        description="Humanization — снижение AI-детектируемости"
    )
    p.add_argument("input",  help="Входной файл (WAV/FLAC после постобработки)")
    p.add_argument("-o", "--output", default=None,
                   help="Выходной файл (default: suffix _human)")
    p.add_argument("--intensity", choices=["ultra-low","low","medium","high"],
                   default="medium",
                   help="Интенсивность обработки (default: medium)")
    p.add_argument("--seed", type=int, default=42,
                   help="Random seed (default: 42, менять для разных вариантов)")
    p.add_argument("--no-noise",   action="store_true",
                   help="Пропустить добавление шума")
    p.add_argument("--no-stretch", action="store_true",
                   help="Пропустить time-stretch")
    p.add_argument("--format", choices=["flac","wav"], default="flac")
    
    args = p.parse_args()
    
    src = Path(args.input)
    if not src.exists():
        print(f"[ERR] Не найден: {src}")
        sys.exit(1)
    
    if args.output:
        dst = Path(args.output)
    else:
        dst = src.parent / f"{src.stem}_human.{args.format}"
    
    print(f"\n{'═'*55}")
    print(f"  HUMANIZATION  [{args.intensity.upper()}]")
    print(f"  {src.name}  →  {dst.name}")
    print(f"{'═'*55}\n")
    
    humanize(src, dst,
             preset=args.intensity,
             seed=args.seed,
             skip_noise=args.no_noise,
             skip_stretch=args.no_stretch)
    
    print(f"\n{'═'*55}")
    print(f"  ГОТОВО. Попробуй разные --seed для вариантов.")
    print(f"{'═'*55}\n")


if __name__ == "__main__":
    main()
