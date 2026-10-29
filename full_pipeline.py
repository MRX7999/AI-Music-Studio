#!/usr/bin/env python3
"""
full_pipeline.py — полный пайплайн для аудио-трека:

  1. Принимает ALAC (.m4a) или любой формат
  2. Показывает спектральный анализ ДО обработки (PNG)
  3. Конвертирует → WAV 44.1 kHz
  4. Запускает AudioSR (48 kHz, 50 DDIM steps)
  5. Постобработка: LFR-шов / de-esser / HiFi-GAN срез / нормализация / дитеринг
  6. Транскрибирует через Whisper medium → .txt + встраивает в метаданные
  7. Показывает спектральный анализ ПОСЛЕ обработки (PNG)
  8. Сохраняет финальный ALAC (.m4a, lossless) или FLAC

Установка:
    pip install audiosr==0.0.7 openai-whisper librosa soundfile numpy scipy tqdm matplotlib
    # На M-чипах: torch уже есть, mps будет использоваться автоматически

Использование:
    python full_pipeline.py input.m4a
    python full_pipeline.py input.m4a -o output.m4a --device mps
    python full_pipeline.py input.m4a --steps 50 --no-audiosr   # только постобработка + whisper
"""

import argparse
import os
import sys
import subprocess
import tempfile
import warnings
warnings.filterwarnings('ignore')

from pathlib import Path
import numpy as np
from humanize import humanize as do_humanize, PRESETS as HUMANIZE_PRESETS

# ── Ленивые импорты (не падать если что-то не стоит) ─────────
def _import(name):
    import importlib
    try:
        return importlib.import_module(name)
    except ImportError:
        print(f"[ERR] Не установлен пакет: {name}")
        print(f"      pip install {name.replace('_','-')}")
        sys.exit(1)


# ══════════════════════════════════════════════════════════════
#  СПЕКТРАЛЬНЫЙ АНАЛИЗ + ВИЗУАЛИЗАЦИЯ
# ══════════════════════════════════════════════════════════════

def spectral_report(wav_path: Path, title: str, out_png: Path):
    """
    Строит три графика:
      • Waveform + RMS огибающая
      • Mel-спектрограмма (0–24kHz)
      • Средний спектр (log scale) с маркерами диапазонов
    Возвращает dict с цифрами анализа.
    """
    librosa = _import('librosa')
    np2    = _import('numpy')
    mpl    = _import('matplotlib')
    mpl.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    import soundfile as sf

    y_raw, sr = sf.read(str(wav_path), always_2d=True)
    y_raw = y_raw.T  # (ch, samples)
    y_mono = librosa.to_mono(y_raw.astype(np.float32))

    dur = y_raw.shape[1] / sr
    peak_dbfs = 20 * np.log10(np.max(np.abs(y_mono)) + 1e-12)

    rms_frames = librosa.feature.rms(y=y_mono, frame_length=2048, hop_length=512)[0]
    rms_db     = librosa.amplitude_to_db(rms_frames, ref=np.max)
    times_rms  = librosa.frames_to_time(np.arange(len(rms_frames)), sr=sr, hop_length=512)

    # ── Spectral stats ───────────────────────────────────────
    n_fft = 32768
    S     = np.abs(librosa.stft(y_mono, n_fft=n_fft))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    avg_mag = np.mean(S, axis=1)
    avg_db  = 20 * np.log10(avg_mag + 1e-12)

    def band_pct(lo, hi):
        m = (freqs >= lo) & (freqs < hi)
        total = np.sum(avg_mag ** 2) + 1e-30
        return np.sum(avg_mag[m] ** 2) / total * 100

    bands = [
        (20,   80,    'Sub'),
        (80,   250,   'Bass'),
        (250,  500,   'Lo-mid'),
        (500,  2000,  'Mid'),
        (2000, 4000,  'Hi-mid'),
        (4000, 8000,  'Presence'),
        (8000, 16000, 'Brilliance'),
        (16000,24000, 'Air'),
    ]

    # Найти частоту резкого обрыва
    cutoff_note = "нет"
    prev = None
    for lo in range(10000, int(sr/2), 500):
        hi = lo + 500
        m = (freqs >= lo) & (freqs < hi)
        m2 = (freqs >= lo-500) & (freqs < lo)
        if m.sum() == 0 or m2.sum() == 0:
            continue
        cur_db  = 20 * np.log10(np.mean(avg_mag[m])  + 1e-12)
        prev_db = 20 * np.log10(np.mean(avg_mag[m2]) + 1e-12)
        if prev_db > -60 and (cur_db - prev_db) < -20:
            cutoff_note = f"~{lo} Hz (спад {cur_db-prev_db:.0f} dB)"
            break

    stats = {
        'sr':          sr,
        'channels':    y_raw.shape[0],
        'duration':    dur,
        'peak_dbfs':   peak_dbfs,
        'rms_mean_db': float(np.mean(rms_db)),
        'cutoff':      cutoff_note,
        'bands':       {n: band_pct(lo, hi) for lo, hi, n in bands},
    }

    # ── Рисуем ───────────────────────────────────────────────
    fig = plt.figure(figsize=(15, 11), facecolor='#0e0e0e')
    gs  = gridspec.GridSpec(3, 1, hspace=0.42, figure=fig)

    C = dict(wave='#00e5ff', rms='#ff6f00', spec_line='#7c4dff',
             cut='#ff1744', grid='#1e1e1e', text='#cccccc')

    # — Waveform —
    ax1 = fig.add_subplot(gs[0])
    ax1.set_facecolor('#111')
    t = np.linspace(0, dur, y_raw.shape[1])
    ax1.plot(t, y_mono, color=C['wave'], lw=0.25, alpha=0.8, label='Waveform')
    ax1.plot(times_rms, rms_frames * np.max(np.abs(y_mono)) / (np.max(rms_frames)+1e-9),
             color=C['rms'], lw=1.2, alpha=0.85, label='RMS env')
    ax1.set_xlim(0, dur)
    ax1.set_title(f'{title}  |  {sr} Hz  |  {y_raw.shape[0]}ch  |  '
                  f'{dur/60:.1f} min  |  Peak {peak_dbfs:.1f} dBFS',
                  color=C['text'], fontsize=11, pad=6)
    ax1.set_ylabel('Amplitude', color=C['text'], fontsize=9)
    ax1.tick_params(colors=C['text'], labelsize=8)
    [s.set_edgecolor('#333') for s in ax1.spines.values()]
    ax1.legend(loc='upper right', facecolor='#1a1a1a', labelcolor=C['text'],
               fontsize=8, framealpha=0.8)
    ax1.grid(True, color=C['grid'], lw=0.4)

    # — Mel spectrogram —
    ax2 = fig.add_subplot(gs[1])
    ax2.set_facecolor('#111')
    fmax = min(sr // 2, 24000)
    Mel = librosa.feature.melspectrogram(y=y_mono, sr=sr, n_mels=256, fmax=fmax)
    Mel_db = librosa.power_to_db(Mel, ref=np.max)
    import librosa.display
    img = librosa.display.specshow(Mel_db, sr=sr, x_axis='time',
                                   y_axis='mel', fmax=fmax, ax=ax2, cmap='inferno')
    # Маркер обрыва если найден
    if cutoff_note != "нет":
        try:
            cf = int(cutoff_note.split('~')[1].split(' ')[0])
            ax2.axhline(cf, color=C['cut'], lw=1.5, ls='--',
                        label=f'Cutoff ~{cf//1000}kHz')
            ax2.legend(loc='upper right', facecolor='#1a1a1a',
                       labelcolor=C['text'], fontsize=8)
        except Exception:
            pass
    ax2.set_title('Mel Spectrogram', color=C['text'], fontsize=10, pad=5)
    ax2.set_ylabel('Frequency (Hz)', color=C['text'], fontsize=9)
    ax2.tick_params(colors=C['text'], labelsize=8)
    [s.set_edgecolor('#333') for s in ax2.spines.values()]
    cbar = plt.colorbar(img, ax=ax2, format='%+2.0f dB', pad=0.01)
    cbar.ax.yaxis.set_tick_params(color=C['text'], labelcolor=C['text'])

    # — Spectrum —
    ax3 = fig.add_subplot(gs[2])
    ax3.set_facecolor('#111')
    mask = freqs > 20
    ax3.semilogx(freqs[mask], avg_db[mask], color=C['spec_line'], lw=1.0)
    ax3.fill_between(freqs[mask], avg_db[mask], avg_db[mask].min() - 5,
                     alpha=0.2, color=C['spec_line'])
    # Полосы
    zone_colors = ['#f44336','#ff9800','#ffeb3b','#4caf50',
                   '#00bcd4','#2196f3','#9c27b0','#e91e63']
    ybot = ax3.get_ylim()[0] if ax3.get_ylim()[0] != 0 else -100
    for i, (lo, hi, name) in enumerate(bands):
        if hi <= sr // 2:
            ax3.axvspan(lo, hi, alpha=0.06, color=zone_colors[i])
            mid = np.sqrt(lo * hi)
            ax3.text(mid, avg_db.max() + 1, name, color=zone_colors[i],
                     fontsize=6.5, ha='center', va='bottom', rotation=0)
    if cutoff_note != "нет":
        try:
            cf = int(cutoff_note.split('~')[1].split(' ')[0])
            ax3.axvline(cf, color=C['cut'], lw=1.5, ls='--',
                        label=f'Cutoff ~{cf//1000}kHz')
            ax3.legend(loc='upper right', facecolor='#1a1a1a',
                       labelcolor=C['text'], fontsize=8)
        except Exception:
            pass
    ax3.set_xlim(20, sr // 2)
    ax3.set_xlabel('Frequency (Hz)', color=C['text'], fontsize=9)
    ax3.set_ylabel('Magnitude (dB)', color=C['text'], fontsize=9)
    ax3.set_title('Average Spectrum (log scale)', color=C['text'], fontsize=10, pad=5)
    ax3.tick_params(colors=C['text'], labelsize=8)
    [s.set_edgecolor('#333') for s in ax3.spines.values()]
    ax3.grid(True, color=C['grid'], lw=0.4)

    # Аннотация с цифрами
    info_lines = [
        f"RMS mean: {stats['rms_mean_db']:.1f} dB",
        f"Cutoff: {stats['cutoff']}",
    ] + [f"{n}: {v:.1f}%" for _, _, n in bands
         for k, v in [('k', stats['bands'].get(n, 0))] if n == k or True]
    # Чище:
    band_txt = "  ".join(f"{n} {stats['bands'][n]:.0f}%" for _, _, n in bands)
    ax3.text(0.01, 0.02, f"RMS {stats['rms_mean_db']:.1f} dB  |  Cutoff: {stats['cutoff']}\n{band_txt}",
             transform=ax3.transAxes, color='#888', fontsize=7, va='bottom',
             fontfamily='monospace')

    plt.savefig(str(out_png), dpi=150, bbox_inches='tight', facecolor='#0e0e0e')
    plt.close(fig)

    return stats


# ══════════════════════════════════════════════════════════════
#  DSP ПОСТОБРАБОТКА (inline, без отдельного файла)
# ══════════════════════════════════════════════════════════════

def butter_filt(audio, cutoff, fs, btype='low', order=8):
    from scipy.signal import butter, sosfiltfilt
    nyq = fs / 2.0
    Wn  = [c / nyq for c in cutoff] if isinstance(cutoff, (list,tuple)) else cutoff / nyq
    sos = butter(order, Wn, btype=btype, output='sos')
    return sosfiltfilt(sos, audio, axis=-1)

def highshelf(audio, freq, gain_db, fs, q=0.707):
    from scipy.signal import sosfiltfilt
    A   = 10 ** (gain_db / 40.0)
    w0  = 2 * np.pi * freq / fs
    alp = np.sin(w0) / (2 * q)
    b0  =  A*((A+1)+(A-1)*np.cos(w0)+2*np.sqrt(A)*alp)
    b1  = -2*A*((A-1)+(A+1)*np.cos(w0))
    b2  =  A*((A+1)+(A-1)*np.cos(w0)-2*np.sqrt(A)*alp)
    a0  =    (A+1)-(A-1)*np.cos(w0)+2*np.sqrt(A)*alp
    a1  =  2*((A-1)-(A+1)*np.cos(w0))
    a2  =    (A+1)-(A-1)*np.cos(w0)-2*np.sqrt(A)*alp
    sos = np.array([[b0/a0, b1/a0, b2/a0, 1.0, a1/a0, a2/a0]])
    return sosfiltfilt(sos, audio, axis=-1)

def spectral_smooth_lfr(audio, sr, boundary=18000, width=1500):
    librosa = _import('librosa')
    n_fft, hop = 4096, 1024
    result = np.zeros_like(audio)
    for ch in range(audio.shape[0]):
        D  = librosa.stft(audio[ch], n_fft=n_fft, hop_length=hop)
        fr = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
        mg, ph = np.abs(D), np.angle(D)
        lo_b = np.searchsorted(fr, boundary - width)
        hi_b = np.searchsorted(fr, boundary + width)
        bd_b = np.searchsorted(fr, boundary)
        bw_b = max(1, (hi_b - lo_b) // 2)
        for b in range(lo_b, min(hi_b, len(fr))):
            w  = max(0.0, 1.0 - abs(b - bd_b) / (bw_b + 1))
            sm = np.convolve(mg[b], np.ones(9)/9, mode='same')
            mg[b] = mg[b] * (1 - w*0.55) + sm * (w*0.55)
        result[ch] = librosa.istft(mg * np.exp(1j * ph),
                                   hop_length=hop, length=audio.shape[1])
    return result

def deesser(audio, sr, lo=6000, hi=12000, thresh=-18.0, ratio=3.5,
            atk_ms=2.0, rel_ms=80.0):
    result = np.zeros_like(audio)
    for ch in range(audio.shape[0]):
        band = butter_filt(audio[ch], [lo, hi], sr, btype='band', order=4)
        frm  = max(64, int(sr * 0.002))
        env  = np.convolve(np.abs(band), np.ones(frm)/frm, mode='same')
        edb  = 20 * np.log10(env + 1e-12)
        gr   = np.zeros_like(edb)
        ov   = edb - thresh
        gr[ov > 0] = -ov[ov > 0] * (1 - 1/ratio)
        atk = int(atk_ms * sr / 1000)
        rel = int(rel_ms * sr / 1000)
        grs = np.zeros_like(gr)
        for i in range(1, len(gr)):
            c = np.exp(-1.0/atk) if gr[i] < grs[i-1] else np.exp(-1.0/rel)
            grs[i] = gr[i] + c * (grs[i-1] - gr[i])
        result[ch] = audio[ch] * 10**(grs/20.0)
    return result

def peak_norm(audio, target_db=-1.0):
    pk = np.max(np.abs(audio))
    if pk < 1e-9: return audio
    return audio * (10**(target_db/20.0) / pk)

def tpdf_dither(audio, bits=24):
    lsb = 2**(1-bits)
    return audio + np.random.uniform(-lsb, lsb, audio.shape) \
                 + np.random.uniform(-lsb, lsb, audio.shape)

def postprocess(audio: np.ndarray, sr: int) -> np.ndarray:
    """Все 5 шагов постобработки"""
    print("    ├─ [1/5] LFR-шов сглаживание @ 18kHz...")
    audio = spectral_smooth_lfr(audio, sr, boundary=18000, width=1500)
    print("    ├─ [2/5] De-esser 6–12kHz...")
    audio = deesser(audio, sr, lo=6000, hi=12000, thresh=-18.0, ratio=3.5)
    print("    ├─ [3/5] HiFi-GAN highshelf -2.5dB @ 19kHz...")
    audio = highshelf(audio, 19000, -2.5, sr)
    print("    ├─ [4/5] Peak normalize → -1.0 dBFS...")
    audio = peak_norm(audio, -1.0)
    print("    └─ [5/5] TPDF dither 24-bit...")
    audio = tpdf_dither(audio, 24)
    return np.clip(audio, -1.0, 1.0)


# ══════════════════════════════════════════════════════════════
#  AUDIOSR  (Python API + чанкинг, моно-обработка, cosine fade)
# ══════════════════════════════════════════════════════════════

CHUNK_SEC   = 10.24  # увеличен с 5.12 → меньше стыков, меньше артефактов
OVERLAP_SEC = 0.5    # увеличен для плавнее cosine crossfade

def _load_wav_sf(path: Path):
    """Загружает WAV через soundfile → (numpy float32, sr)"""
    import soundfile as sf
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return data, sr   # shape (samples, channels)

def _save_wav_sf(path: Path, data, sr: int):
    import soundfile as sf
    sf.write(str(path), data, sr, subtype="FLOAT")

def _cosine_fade(n: int):
    """Cosine fade-in/out — плавнее линейного, нет щелчков на стыках"""
    t = np.linspace(0.0, np.pi, n)
    fade_out = (1.0 + np.cos(t)) * 0.5      # 1→0 по косинусу
    fade_in  = (1.0 - np.cos(t)) * 0.5      # 0→1 по косинусу
    return fade_in[:, np.newaxis], fade_out[:, np.newaxis]

def run_audiosr(wav_in: Path, out_dir: Path, steps: int, guidance: float,
                device: str, seed: int) -> Path:
    """
    Чанковый AudioSR через Python API.
    Ключевые улучшения vs предыдущей версии:
    - Чанки 10.24 с вместо 5.12 с → ~вдвое меньше стыков
    - Моно-обработка: L+R → моно → AudioSR → восстановить стерео-ширину
      (оба канала одинаково апскейлены, нет расхождения фаз)
    - Cosine crossfade вместо линейного → нет щелчков
    - guidance_scale и ddim_steps берутся из args (снижены по умолчанию)
    """
    import soundfile as sf

    print(f"    Загрузка аудио: {wav_in.name}")
    data, sr_in = _load_wav_sf(wav_in)          # (samples, ch)
    n_ch = data.shape[1]
    total_samples = data.shape[0]
    duration_total = total_samples / sr_in
    print(f"    Длительность: {duration_total:.1f}s  |  sr={sr_in}  |  каналов={n_ch}")
    print(f"    Параметры: {steps} шагов, guidance={guidance:.1f}")
    print(f"    Чанк: {CHUNK_SEC}s, перекрытие: {OVERLAP_SEC}s")

    # --- загружаем модель один раз ---
    print(f"    Загрузка модели AudioSR (basic, {device})...")
    from audiosr import build_model, super_resolution
    audiosr_model = build_model(model_name="basic", device=device)

    chunk_sz   = int(CHUNK_SEC   * sr_in)
    overlap_sz = int(OVERLAP_SEC * sr_in)
    hop_sz     = chunk_sz - overlap_sz
    SR_OUT = 48000

    # ── Стратегия: обрабатываем МИД (сумму каналов) через AudioSR,
    #    потом восстанавливаем стерео-ширину через САЙД-компонент оригинала.
    #    Это сохраняет тембр и динамику лучше, чем обработка каждого канала отдельно.
    if n_ch >= 2:
        mono_data = (data[:, 0] + data[:, 1]) * 0.5   # Mid
        side_data =  data[:, 0] - data[:, 1]           # Side (оригинал)
    else:
        mono_data = data[:, 0]
        side_data = None

    out_chunks_48k = []
    pos = 0
    chunk_idx = 0
    while pos < total_samples:
        end = min(pos + chunk_sz, total_samples)
        chunk_mono = mono_data[pos:end]

        tmp_wav = out_dir / f"_chunk_{chunk_idx}.wav"
        sf.write(str(tmp_wav), chunk_mono, sr_in, subtype="FLOAT")

        wf_48k = super_resolution(
            audiosr_model,
            str(tmp_wav),
            seed=seed + chunk_idx,
            ddim_steps=steps,
            guidance_scale=guidance,
            latent_t_per_second=12.8,
        )

        if hasattr(wf_48k, "cpu"):
            wf_48k = wf_48k.squeeze().cpu().numpy()
        else:
            wf_48k = wf_48k.squeeze()  # (samples_48k,)

        out_chunks_48k.append(wf_48k)
        tmp_wav.unlink(missing_ok=True)

        chunk_idx += 1
        elapsed_pct = end / total_samples * 100
        print(f"    Чанк {chunk_idx}: [{pos/sr_in:.1f}s – {end/sr_in:.1f}s]  {elapsed_pct:.0f}%",
              flush=True)

        if end >= total_samples:
            break
        pos += hop_sz

    # --- cosine crossfade склейка ---
    print(f"    Склейка {len(out_chunks_48k)} чанков (cosine fade)...")
    overlap_48k = int(OVERLAP_SEC * SR_OUT)

    if len(out_chunks_48k) == 1:
        mid_48k = out_chunks_48k[0]
    else:
        mid_48k = out_chunks_48k[0]
        for nxt in out_chunks_48k[1:]:
            ov = min(overlap_48k, len(mid_48k), len(nxt))
            if ov > 0:
                fade_in, fade_out = _cosine_fade(ov)
                fade_in  = fade_in.squeeze()
                fade_out = fade_out.squeeze()
                mid_48k[-ov:] = mid_48k[-ov:] * fade_out + nxt[:ov] * fade_in
                mid_48k = np.concatenate([mid_48k, nxt[ov:]])
            else:
                mid_48k = np.concatenate([mid_48k, nxt])

    # --- восстанавливаем стерео ---
    if side_data is not None:
        # Ресэмплируем side до 48k чтобы длины совпали
        import librosa
        side_48k = librosa.resample(side_data.astype(np.float32),
                                    orig_sr=sr_in, target_sr=SR_OUT)
        # Выравниваем длину
        min_len = min(len(mid_48k), len(side_48k))
        mid_48k  = mid_48k[:min_len]
        side_48k = side_48k[:min_len]

        # Слегка уменьшаем ширину сайда (AudioSR немного добавил HF → компенсируем)
        side_scale = 0.85
        L = mid_48k + side_48k * side_scale
        R = mid_48k - side_48k * side_scale
        result_48k = np.stack([L, R], axis=1)  # (samples, 2)
    else:
        result_48k = mid_48k[:, np.newaxis]    # (samples, 1) моно

    out_wav = out_dir / "output_48K.wav"
    _save_wav_sf(out_wav, result_48k, SR_OUT)
    print(f"    ✅ AudioSR завершён → {out_wav.name}  ({result_48k.shape[0]/SR_OUT:.1f}s)")
    return out_wav


# ══════════════════════════════════════════════════════════════
#  WHISPER ТРАНСКРИПЦИЯ
# ══════════════════════════════════════════════════════════════

def transcribe(wav_path: Path, device: str) -> dict:
    """
    Запускает Whisper medium, возвращает:
      text        — полный текст
      language    — определённый язык
      segments    — список dict(start, end, text)
      lrc         — строки в формате LRC [mm:ss.xx] text
      srt         — текст в формате SRT
    """
    try:
        import whisper
    except ImportError:
        print("    [WARN] openai-whisper не установлен. pip install openai-whisper")
        return None

    print(f"    Загрузка модели Whisper medium...")
    wdev = "cpu"  # mps не поддерживается whisper напрямую, используем cpu
    if device == "cuda":
        wdev = "cuda"
    model = whisper.load_model("medium", device=wdev)

    print(f"    Транскрибирование ({wav_path.name})...")
    result = model.transcribe(
        str(wav_path),
        task="transcribe",
        verbose=False,
        word_timestamps=True,
    )

    lang  = result.get("language", "unknown")
    text  = result.get("text", "").strip()
    segs  = result.get("segments", [])

    # LRC
    lrc_lines = []
    for s in segs:
        mm  = int(s['start']) // 60
        ss  = s['start'] - mm * 60
        lrc_lines.append(f"[{mm:02d}:{ss:05.2f}]{s['text'].strip()}")

    # SRT
    def ts_srt(t):
        h = int(t) // 3600
        m = (int(t) % 3600) // 60
        s = t - h*3600 - m*60
        return f"{h:02d}:{m:02d}:{s:06.3f}".replace('.', ',')

    srt_blocks = []
    for i, s in enumerate(segs, 1):
        srt_blocks.append(
            f"{i}\n{ts_srt(s['start'])} --> {ts_srt(s['end'])}\n{s['text'].strip()}\n"
        )

    return {
        'text':     text,
        'language': lang,
        'segments': segs,
        'lrc':      "\n".join(lrc_lines),
        'srt':      "\n".join(srt_blocks),
    }


# ══════════════════════════════════════════════════════════════
#  FFMPEG УТИЛИТЫ
# ══════════════════════════════════════════════════════════════

def to_wav(src: Path, dst: Path, sr: int = 44100):
    subprocess.run([
        "ffmpeg", "-y", "-i", str(src),
        "-ar", str(sr), "-ac", "2", "-sample_fmt", "s16",
        str(dst), "-loglevel", "error"
    ], check=True)

def wav_to_alac(wav: Path, dst: Path, metadata: dict = None, cover: Path = None):
    """WAV → M4A ALAC (Apple Lossless) с метаданными и обложкой"""
    meta_args = []
    if metadata:
        for k, v in metadata.items():
            if v:  # пропускаем пустые значения
                meta_args += ["-metadata", f"{k}={v}"]

    if cover and cover.exists():
        subprocess.run([
            "ffmpeg", "-y",
            "-i", str(wav),
            "-i", str(cover),
            "-c:a", "alac",
            "-map", "0:a", "-map", "1:v",
            "-c:v", "copy",
            "-disposition:v", "attached_pic",
            *meta_args,
            str(dst), "-loglevel", "error"
        ], check=True)
    else:
        subprocess.run([
            "ffmpeg", "-y", "-i", str(wav),
            "-c:a", "alac",
            *meta_args,
            str(dst), "-loglevel", "error"
        ], check=True)

def wav_to_flac(wav: Path, dst: Path, metadata: dict = None, cover: Path = None):
    meta_args = []
    if metadata:
        for k, v in metadata.items():
            if v:
                meta_args += ["-metadata", f"{k}={v}"]
    if cover and cover.exists():
        subprocess.run([
            "ffmpeg", "-y",
            "-i", str(wav),
            "-i", str(cover),
            "-c:a", "flac", "-compression_level", "8",
            "-map", "0:a", "-map", "1:v",
            "-c:v", "copy",
            "-disposition:v", "attached_pic",
            *meta_args,
            str(dst), "-loglevel", "error"
        ], check=True)
    else:
        subprocess.run([
            "ffmpeg", "-y", "-i", str(wav),
            "-c:a", "flac", "-compression_level", "8",
            *meta_args,
            str(dst), "-loglevel", "error"
        ], check=True)

def embed_lyrics(src: Path, dst: Path, lyrics: str, title: str = ""):
    """Встроить текст как lyrics/unsyncedlyrics в M4A/FLAC"""
    subprocess.run([
        "ffmpeg", "-y", "-i", str(src),
        "-c", "copy",
        "-metadata", f"lyrics={lyrics}",
        "-metadata", f"comment=Transcribed by Whisper medium",
        str(dst), "-loglevel", "error"
    ], check=True)


# ══════════════════════════════════════════════════════════════
#  ГЛАВНЫЙ ПАЙПЛАЙН
# ══════════════════════════════════════════════════════════════



def extract_cover(src: Path, dst: Path) -> bool:
    """Извлекает обложку из M4A/MP3/FLAC в PNG/JPG. Возвращает True если успешно."""
    try:
        result = subprocess.run([
            "ffmpeg", "-y", "-i", str(src),
            "-an", "-vcodec", "copy",
            str(dst), "-loglevel", "error"
        ], capture_output=True)
        if result.returncode == 0 and dst.exists() and dst.stat().st_size > 100:
            return True
        # Попробуем через -map 0:v
        result2 = subprocess.run([
            "ffmpeg", "-y", "-i", str(src),
            "-map", "0:v", "-vframes", "1",
            str(dst), "-loglevel", "error"
        ], capture_output=True)
        return result2.returncode == 0 and dst.exists() and dst.stat().st_size > 100
    except Exception:
        return False

def _do_resume_export(wav_ready: Path, dst: Path, stem: str, fmt: str):
    """Берёт готовый WAV и делает только финальный экспорт в ALAC/FLAC."""
    import soundfile as sf_mod
    import tempfile as tmpmod

    if not wav_ready.exists():
        print(f"[ERR] Файл не найден: {wav_ready}")
        import sys; sys.exit(1)

    print(f"\n{'═'*60}")
    print(f"  RESUME EXPORT")
    print(f"  WAV:    {wav_ready}")
    print(f"  ВЫХОД:  {dst}")
    print(f"{'═'*60}")

    info = sf_mod.info(str(wav_ready))
    sr_in = info.samplerate

    if sr_in != 44100:
        print(f"  Ресэмпл {sr_in} → 44100 Hz...")
        ftmp = tmpmod.NamedTemporaryFile(suffix=".wav", delete=False)
        resampled = Path(ftmp.name)
        ftmp.close()
        subprocess.run([
            "ffmpeg", "-y", "-i", str(wav_ready),
            "-ar", "44100", "-acodec", "pcm_s24le",
            str(resampled), "-loglevel", "error"
        ], check=True)
        print("  Ресэмпл готов.")
    else:
        resampled = wav_ready

    # Пробуем найти обложку рядом с dst
    _cover_candidate = dst.parent / f"{stem}_cover.jpg"
    _cover = _cover_candidate if _cover_candidate.exists() else None
    meta = {"title": stem, "comment": "resume-export via full_pipeline.py"}
    if fmt == "alac":
        wav_to_alac(resampled, dst, meta, cover=_cover)
    else:
        wav_to_flac(resampled, dst, meta, cover=_cover)

    size_mb = dst.stat().st_size / 1024**2
    print(f"\n  ✅ Готово: {dst}  ({size_mb:.1f} MB)")
    if sr_in != 44100:
        resampled.unlink(missing_ok=True)


def pipeline(args):
    import soundfile as sf

    src  = Path(args.input)
    stem = src.stem
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Финальное имя
    ext = "m4a" if args.format == "alac" else "flac"
    dst = Path(args.output) if args.output else out_dir / f"{stem}_final.{ext}"

    # ── RESUME MODE ───────────────────────────────────────────────────────────
    if getattr(args, "resume_wav", None):
        _do_resume_export(Path(args.resume_wav), dst, stem, args.format)
        return

    print(f"\n{'═'*60}")
    print(f"  ТРЕК:   {src.name}")
    print(f"  ВЫХОД:  {dst}")
    print(f"  DEVICE: {args.device}")
    print(f"{'═'*60}\n")

    with tempfile.TemporaryDirectory(prefix="fullpipe_") as td:
        tmp = Path(td)

        # ── Извлекаем обложку из исходного файла ─────────────
        cover_img = out_dir / f"{stem}_cover.jpg"
        if not cover_img.exists():
            _has_cover = extract_cover(src, cover_img)
            if _has_cover:
                print(f"    🖼  Обложка извлечена → {cover_img.name}")
            else:
                cover_img = None
                print("    [INFO] Обложка не найдена в исходном файле")
        else:
            print(f"    🖼  Обложка уже есть: {cover_img.name}")

        # ── 1. Конвертировать в WAV для анализа ──────────────
        print("[STEP 1/7] Конвертация в WAV...")
        wav_orig = tmp / "original.wav"
        to_wav(src, wav_orig, sr=44100)

        # ── 2. Спектральный анализ ДО ─────────────────────────
        print("[STEP 2/7] Спектральный анализ ДО обработки...")
        png_before = out_dir / f"{stem}_before.png"
        stats_before = spectral_report(wav_orig, f"{stem} — BEFORE", png_before)
        print(f"    Peak: {stats_before['peak_dbfs']:.2f} dBFS  |  "
              f"Cutoff: {stats_before['cutoff']}")
        print(f"    → {png_before}")

        # ── 3. AudioSR ───────────────────────────────────────
        _ext_wav = getattr(args, "audiosr_wav", None)
        if _ext_wav:
            sr_wav = Path(_ext_wav)
            if not sr_wav.exists():
                print(f"[ERR] --audiosr-wav не найден: {sr_wav}")
                import sys; sys.exit(1)
            print(f"[STEP 3/7] AudioSR — пропущен, используем: {sr_wav.name}")
        elif not args.no_audiosr:
            print(f"\n[STEP 3/7] AudioSR ({args.steps} steps, gs={args.guidance})...")
            sr_dir = tmp / "audiosr"
            sr_dir.mkdir()
            sr_wav = run_audiosr(wav_orig, sr_dir, args.steps,
                                 args.guidance, args.device, args.seed)
            print(f"    → {sr_wav.name}")
            # 💾 Сохраняем копию в out_dir — не потеряем при падении
            import shutil as _shutil
            sr_backup = out_dir / f"{stem}_audiosr_48k.wav"
            _shutil.copy2(sr_wav, sr_backup)
            print(f"    💾 Резервная копия: {sr_backup}")
        else:
            print("[STEP 3/7] AudioSR — пропущен (--no-audiosr)")
            sr_wav = wav_orig

        # ── 4. Постобработка ─────────────────────────────────
        print("\n[STEP 4/7] Постобработка артефактов...")
        audio_raw, sr_rate = sf.read(str(sr_wav), always_2d=True)
        audio = audio_raw.T.astype(np.float64)
        audio = postprocess(audio, sr_rate)
        wav_clean = tmp / "clean.wav"
        sf.write(str(wav_clean), audio.T, sr_rate, subtype='PCM_24')
        print(f"    → {wav_clean.name}")

        # ── 5. Спектральный анализ ПОСЛЕ ──────────────────────
        print("\n[STEP 5/7] Спектральный анализ ПОСЛЕ обработки...")
        png_after = out_dir / f"{stem}_after.png"
        stats_after = spectral_report(wav_clean, f"{stem} — AFTER", png_after)
        print(f"    Peak: {stats_after['peak_dbfs']:.2f} dBFS  |  "
              f"Cutoff: {stats_after['cutoff']}")
        print(f"    → {png_after}")

        # ── 6. Whisper транскрипция ───────────────────────────
        print("\n[STEP 6/7] Whisper medium — транскрипция...")
        # Whisper лучше работает с 16kHz mono WAV
        wav_for_whisper = tmp / "whisper_in.wav"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(wav_clean),
            "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
            str(wav_for_whisper), "-loglevel", "error"
        ], check=True)
        transcript = transcribe(wav_for_whisper, args.device)

        if transcript:
            lang = transcript['language']
            txt  = transcript['text']
            print(f"\n    Язык: {lang}")
            print(f"    {'─'*50}")
            # Показать первые 400 символов
            preview = txt[:400] + ("..." if len(txt) > 400 else "")
            for line in preview.split('\n'):
                print(f"    {line}")
            print(f"    {'─'*50}")

            # Сохранить файлы с текстом
            txt_file = out_dir / f"{stem}_lyrics.txt"
            lrc_file = out_dir / f"{stem}.lrc"
            srt_file = out_dir / f"{stem}.srt"

            txt_file.write_text(
                f"[{stem}]\n"
                f"Language: {lang}\n"
                f"Transcribed by: Whisper medium\n\n"
                f"{txt}\n",
                encoding='utf-8'
            )
            lrc_file.write_text(
                f"[ti:{stem}]\n[by:Whisper medium]\n\n" + transcript['lrc'],
                encoding='utf-8'
            )
            srt_file.write_text(transcript['srt'], encoding='utf-8')

            print(f"\n    Сохранены: {txt_file.name} | {lrc_file.name} | {srt_file.name}")
        else:
            transcript = {'text': '', 'language': 'unknown'}

        # ── 7. Humanization ──────────────────────────────────
        if not args.no_humanize:
            print(f"\n[STEP 7/8] Humanization [{args.humanize_intensity.upper()}]...")
            wav_humanized = tmp / "humanized.wav"
            do_humanize(
                wav_clean, wav_humanized,
                preset=args.humanize_intensity,
                seed=args.seed,
                skip_noise=args.no_noise,
                skip_stretch=False,
                verbose=True,
            )
            wav_final = wav_humanized
            # Спектр после humanization
            png_human = out_dir / f"{stem}_humanized.png"
            stats_human = spectral_report(wav_humanized, f"{stem} — HUMANIZED", png_human)
            print(f"    Peak: {stats_human['peak_dbfs']:.2f} dBFS  |  Cutoff: {stats_human['cutoff']}")
            print(f"    → {png_human}")
        else:
            print("\n[STEP 7/8] Humanization — пропущен (--no-humanize)")
            wav_final = wav_clean

        # ── 8. Финальный экспорт ─────────────────────────────
        print(f"\n[STEP 8/8] Экспорт → {ext.upper()}...")

        # Ресэмпл 48k → 44.1k если нужно
        if sr_rate != 44100:
            wav_resampled = tmp / "resampled.wav"
            subprocess.run([
                "ffmpeg", "-y", "-i", str(wav_final),
                "-ar", "44100", "-acodec", "pcm_s24le",
                str(wav_resampled), "-loglevel", "error"
            ], check=True)
        else:
            wav_resampled = wav_final

        meta = {
            "title":   stem,
            "comment": f"AudioSR {args.steps}steps | Humanize {args.humanize_intensity} | Whisper | lang={transcript['language']}",
            "lyrics":  transcript['text'][:4000] if transcript['text'] else '',
        }

        if args.format == "alac":
            wav_to_alac(wav_resampled, dst, meta, cover=cover_img)
        else:
            wav_to_flac(wav_resampled, dst, meta, cover=cover_img)

        size_mb = dst.stat().st_size / 1024**2
        print(f"    → {dst} ({size_mb:.1f} MB)")

    # ── Итог ─────────────────────────────────────────────────
    print(f"\n{'═'*60}")
    print(f"  ГОТОВО")
    print(f"  Аудио:        {dst}")
    print(f"  Спектр до:    {out_dir / (stem + '_before.png')}")
    print(f"  Спектр после: {out_dir / (stem + '_after.png')}")
    if not args.no_humanize:
        print(f"  Спектр human: {out_dir / (stem + '_humanized.png')}")
    if transcript and transcript['text']:
        print(f"  Текст:        {out_dir / (stem + '_lyrics.txt')}")
        print(f"  LRC:          {out_dir / (stem + '.lrc')}")
        print(f"  SRT:          {out_dir / (stem + '.srt')}")
    print(f"{'═'*60}\n")


# ══════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════

def auto_device():
    try:
        import torch
        if torch.cuda.is_available(): return "cuda"
        if torch.backends.mps.is_available(): return "mps"
    except ImportError:
        pass
    return "cpu"

def main():
    p = argparse.ArgumentParser(
        description="Полный пайплайн: ALAC → AudioSR → постобработка → Whisper → ALAC/FLAC"
    )
    p.add_argument("input",  help="Входной файл (.m4a ALAC, .wav, .flac, .mp3...)")
    p.add_argument("-o", "--output", default=None,
                   help="Выходной файл (default: рядом со входным, суффикс _final)")
    p.add_argument("--output-dir", default="./pipeline_out",
                   help="Папка для PNG и txt файлов (default: ./pipeline_out)")
    p.add_argument("--format", choices=["alac","flac"], default="alac",
                   help="Формат выхода: alac=M4A lossless, flac=FLAC 24bit")
    p.add_argument("--steps",    type=int,   default=12,
                   help="DDIM шагов для AudioSR (default: 50)")
    p.add_argument("--guidance", type=float, default=2.0,
                   help="Guidance scale AudioSR (default: 3.5)")
    p.add_argument("--seed",     type=int,   default=42)
    p.add_argument("--device",   default=None,
                   help="Устройство: cuda / mps / cpu (default: автоопределение)")
    p.add_argument("--no-audiosr", action="store_true",
                   help="Пропустить AudioSR (только постобработка + Whisper)")
    p.add_argument("--audiosr-wav", dest="audiosr_wav", default=None,
                   metavar="WAV_48K",
                   help="Пропустить AudioSR и использовать готовый 48k WAV. "
                        "Пример: --audiosr-wav pipeline_out/02_audiosr_48k.wav")
    p.add_argument("--no-humanize", action="store_true",
                   help="Пропустить humanization")
    p.add_argument("--humanize-intensity", dest="humanize_intensity",
                   choices=["ultra-low","low","medium","high"], default="low",
                   help="Интенсивность humanization: low/medium/high (default: medium)")
    p.add_argument("--no-noise", action="store_true",
                   help="Пропустить шум в humanization")
    p.add_argument("--resume-from-wav", dest="resume_wav", default=None,
                   metavar="WAV_PATH",
                   help="Пропустить все шаги, только конвертировать готовый WAV → ALAC/FLAC. "
                        "Пример: --resume-from-wav /tmp/fullpipe_xxx/humanized.wav")
    args = p.parse_args()

    if args.device is None:
        args.device = auto_device()
        print(f"[INFO] Устройство: {args.device}")

    pipeline(args)

if __name__ == "__main__":
    main()
