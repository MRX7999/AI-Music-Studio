"""Движок виртуальной записи.

Цепочка канала:
    стем → микрофон (АЧХ, диаграмма, близость, шум) → преамп → гейт → HPF/LPF/4-полосный EQ
         → компрессор (авто или ручной) → ширина стерео → фейдер
         ├─► близкий микрофон (полярность): панорама по положению на сцене → dry-шина
         ├─► комнатная пара (A-B / X-Y / ORTF / NOS / Блюмлейн): прямой звук + ранние отражения → room-шина
         ├─► посыл в диффузный хвост помещения (pre-delay) → reverb-шина
         └─► посыл в дилей (обратная связь, ФНЧ в петле, ping-pong) → delay-шина
Мастер:  dry + room + reverb + delay + эмбиент → ширина стерео → мастер-EQ → bus-компрессор → лента
         → LUFS-нормализация + true-peak лимитер → фейды → дизеринг → файл.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.signal import oaconvolve

from . import dsp
from .audio_io import load_cached, write_audio
from .loudness import integrated_lufs, limiter, normalize_loudness, true_peak_db
from .mics import MICS, PATTERNS, color as mic_color
from .scenes import (ROOM_TECHNIQUES, ambience, critical_distance, late_tail, room_pair, spatial_fir, C_SOUND,
                     SOURCE_Z)
from .session import Channel, Session


class RenderCancelled(Exception):
    pass


@dataclass
class RenderResult:
    audio: np.ndarray
    sr: int
    report: dict = field(default_factory=dict)
    path: Path | None = None
    stems: dict = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────
#  Геометрия для UI и рендера
# ──────────────────────────────────────────────────────────────

def stage_center(session: Session) -> tuple[float, float]:
    x0, y0, x1, y1 = session.scene_preset.stage_rect()
    return (x0 + x1) / 2, (y0 + y1) / 2


def ref_distance(session: Session) -> float:
    lx, ly = session.listener()
    cx, cy = stage_center(session)
    return max(math.hypot(lx - cx, ly - cy), 1.0)


def channel_geometry(session: Session, ch: Channel) -> dict:
    """Расстояние до слушателя, задержка, азимут и авто-панорама канала."""
    lx, ly = session.listener()
    dx, dy = ch.x - lx, ly - ch.y          # сцена «перед» слушателем: y меньше
    dist = math.sqrt(dx * dx + dy * dy + (SOURCE_Z - session.recording.room_height_m) ** 2)
    az = math.degrees(math.atan2(dx, max(dy, 1e-3)))
    auto_pan = float(np.clip(az / 60.0, -1.0, 1.0))
    rt60 = session.rt60
    rc = critical_distance(session.scene_preset, rt60)
    return {
        "distance_m": dist,
        "delay_ms": dist / C_SOUND * 1000.0,
        "azimuth_deg": az,
        "auto_pan": auto_pan,
        "pan": auto_pan if ch.pan is None else float(ch.pan),
        "critical_distance_m": rc,
        "beyond_critical": dist > rc,
    }


def describe_scene(session: Session) -> dict:
    sc = session.scene_preset
    rt60 = session.rt60
    tech = ROOM_TECHNIQUES.get(session.recording.room_technique, ROOM_TECHNIQUES["ab"])
    return {
        "id": session.scene,
        "name": sc.name,
        "size": f"{sc.width:g}×{sc.depth:g}×{sc.height:g} м",
        "width_m": sc.width, "depth_m": sc.depth, "height_m": sc.height,
        "volume_m3": round(sc.volume),
        "rt60_s": round(rt60, 2),
        "critical_distance_m": round(critical_distance(sc, rt60), 2),
        "ref_distance_m": round(ref_distance(session), 2),
        "room_technique": session.recording.room_technique,
        "room_technique_name": tech["name"],
    }


# ──────────────────────────────────────────────────────────────
#  Канал
# ──────────────────────────────────────────────────────────────

def active_channels(session: Session) -> list[Channel]:
    solo = [c for c in session.channels if c.solo]
    pool = solo if solo else session.channels
    return [c for c in pool if not c.mute]


def _slice(audio: np.ndarray, sr: int, start_s: float, duration_s: float | None) -> np.ndarray:
    s = max(0, int(start_s * sr))
    e = audio.shape[1] if duration_s is None else min(audio.shape[1], s + int(duration_s * sr))
    return audio[:, s:e] if s < audio.shape[1] else np.zeros((audio.shape[0], 0))


def channel_eq_bands(ch: Channel) -> list:
    """Полосы канального EQ в формате dsp.apply_eq (HPF/LPF всегда, остальное — если eq_on)."""
    bands = []
    if ch.hpf_hz > 20:
        bands.append(("highpass", ch.hpf_hz, 0.0, 0.707))
    if 20 < ch.lpf_hz < 19000:
        bands.append(("lowpass", ch.lpf_hz, 0.0, 0.707))
    if ch.eq_on:
        if abs(ch.eq_low_db) > 0.05:
            bands.append(("lowshelf", ch.eq_low_freq, ch.eq_low_db, 0.7))
        if abs(ch.eq_lowmid_db) > 0.05:
            bands.append(("peak", ch.eq_lowmid_freq, ch.eq_lowmid_db, max(ch.eq_lowmid_q, 0.1)))
        if abs(ch.eq_mid_db) > 0.05:
            bands.append(("peak", ch.eq_mid_freq, ch.eq_mid_db, max(ch.eq_mid_q, 0.1)))
        if abs(ch.eq_high_db) > 0.05:
            bands.append(("highshelf", ch.eq_high_freq, ch.eq_high_db, 0.7))
    return bands


def process_channel_strip(ch: Channel, audio: np.ndarray, sr: int, session: Session,
                          seed: int = 0) -> tuple[np.ndarray, dict]:
    """Микрофон → преамп → гейт → EQ → компрессор → ширина → фейдер. Вход/выход (ch, n)."""
    rec = session.recording
    mic = MICS.get(ch.mic, MICS["ldc_studio"])
    a = audio if ch.stereo else dsp.to_mono(audio)[np.newaxis, :]
    info: dict = {"mic": mic.name}
    if mic.id != "di":
        a, minfo = mic_color(a, sr, mic, ch.mic_distance_cm / 100.0, ch.mic_angle_deg, seed=seed)
        info.update(minfo)
    a = dsp.preamp(a, sr, rec.preamp, rec.preamp_drive_db + ch.drive_db)
    if ch.gate_on:
        a = dsp.gate(a, sr, threshold_db=ch.gate_threshold_db, range_db=ch.gate_range_db,
                     release_ms=ch.gate_release_ms)
    bands = channel_eq_bands(ch)
    if bands:
        a = dsp.apply_eq(a, sr, bands)
    if ch.comp_mode == "manual":
        if ch.comp_ratio > 1.0:
            a = dsp.compressor(a, sr, threshold_db=ch.comp_threshold_db, ratio=ch.comp_ratio,
                               attack_ms=max(ch.comp_attack_ms, 0.1), release_ms=max(ch.comp_release_ms, 1.0),
                               knee_db=max(ch.comp_knee_db, 0.0), makeup_db=ch.comp_makeup_db)
    elif ch.comp > 0.01:
        a = dsp.compressor(a, sr, threshold_db=-10.0 - 20.0 * ch.comp, ratio=1.0 + 5.0 * ch.comp,
                           attack_ms=8.0 + 20.0 * (1 - ch.comp), release_ms=140.0)
    if a.shape[0] == 2 and abs(ch.width - 1.0) > 1e-6:
        a = dsp.ms_width(a, ch.width)
    a = a * dsp.db_to_gain(ch.gain_db)
    return a, info


def _meter(audio: np.ndarray, sr: int, hop_s: float = 0.05) -> dict:
    """Пик и RMS (дБFS) по окнам hop_s — для индикаторов уровня пульта при прослушивании."""
    a = np.max(np.abs(dsp.as_2d(audio)), axis=0)
    hop = max(1, int(sr * hop_s))
    nb = int(np.ceil(a.shape[0] / hop)) if a.shape[0] else 0
    if nb == 0:
        return {"peak": [], "rms": []}
    pad = np.pad(a, (0, nb * hop - a.shape[0])).reshape(nb, hop)
    peak = 20 * np.log10(np.max(pad, axis=1) + 1e-9)
    rms = 10 * np.log10(np.mean(np.square(pad), axis=1) + 1e-12)
    return {"peak": np.round(np.maximum(peak, -90.0), 1).tolist(),
            "rms": np.round(np.maximum(rms, -90.0), 1).tolist()}


def _pan_to_stereo(a: np.ndarray, pan: float) -> np.ndarray:
    if a.shape[0] == 1:
        gl, gr = dsp.pan_gains(pan)
        return np.vstack([a[0] * gl, a[0] * gr])
    # стерео-источник: баланс, а не сведение в моно
    gl = min(1.0, 1.0 - pan)
    gr = min(1.0, 1.0 + pan)
    return np.vstack([a[0] * gl, a[1] * gr])


# ──────────────────────────────────────────────────────────────
#  Рендер сессии
# ──────────────────────────────────────────────────────────────

def render_session(session: Session, start_s: float = 0.0, duration_s: float | None = None,
                   out_path: str | Path | None = None, sample_rate: int | None = None,
                   export_stems_dir: str | Path | None = None,
                   progress=None, cancel=None, master: bool = True, meters: bool = False) -> RenderResult:
    """Сводит сессию. progress(frac: float, msg: str); cancel() → True для остановки.

    meters=True добавляет в отчёт уровни каналов и мастера по окнам 50 мс (для индикаторов пульта).
    """
    t0 = time.time()
    rec = session.recording
    sr = int(sample_rate or rec.sample_rate)
    scene = session.scene_preset
    rt60 = session.rt60
    rc = critical_distance(scene, rt60)
    lx, ly = session.listener()
    ref = ref_distance(session)
    pair = room_pair(lx, ly, rec.room_technique, rec.pair_spacing_m, rec.room_height_m)
    tech = ROOM_TECHNIQUES.get(rec.room_technique, ROOM_TECHNIQUES["ab"])
    pair_ree = PATTERNS[tech["pattern"]]["ree"]
    align = int(round(ref / C_SOUND * sr)) if rec.align_room_mics else 0
    room_lin = dsp.db_to_gain(rec.room_mics_db) if (rt60 > 0 or scene.early_db > -100) else 0.0
    if scene.id == "dry":
        room_lin = 0.0

    def tick(frac, msg):
        if cancel and cancel():
            raise RenderCancelled()
        if progress:
            progress(float(min(max(frac, 0.0), 1.0)), msg)

    chans = active_channels(session)
    if not chans:
        raise ValueError("Нет активных каналов: добавьте трек или снимите Mute/Solo")

    sources = {}
    n = 0
    for i, ch in enumerate(chans):
        tick(0.02 + 0.08 * i / len(chans), f"Загрузка: {ch.name}")
        a = dsp.as_2d(load_cached(ch.source, sr))
        if a.shape[0] > 2:
            a = a[:2]
        a = _slice(a, sr, start_s, duration_s)
        sources[ch.id] = a
        n = max(n, a.shape[1])
    if n == 0:
        raise ValueError("Пустой фрагмент: начало превью дальше конца трека")

    tail = late_tail(scene, sr, rt60, seed=rec.seed) if rt60 > 0.02 else None
    predelay = int(round(sr * max(rec.predelay_ms, 0.0) / 1000.0))
    if tail is not None and predelay > 0:
        tail = np.pad(tail, ((0, 0), (predelay, 0)))
    use_delay = any(c.delay_send_db > -59.9 for c in chans)
    d_ir = dsp.delay_ir(sr, rec.delay_time_ms, rec.delay_feedback, rec.delay_hicut_hz, rec.delay_pingpong) \
        if use_delay else None
    tail_len_pad = 0
    if duration_s is None:
        longest = max(tail.shape[1] if tail is not None else 0, d_ir[0].shape[0] if d_ir is not None else 0)
        tail_len_pad = min(longest, int(sr * max(rec.tail_s, 0.0)))
    total = n + tail_len_pad

    dry = np.zeros((2, total))
    room = np.zeros((2, total))
    send = np.zeros(total)
    dsend = np.zeros((2, total)) if use_delay else None
    ch_reports = []
    ch_meters = {}
    stems_out = {}

    for i, ch in enumerate(chans):
        base = 0.1 + 0.6 * i / len(chans)
        tick(base, f"Канал: {ch.name}")
        a = dsp.match_length(sources[ch.id], n)
        strip, info = process_channel_strip(ch, a, sr, session, seed=rec.seed + i * 31)
        geo = channel_geometry(session, ch)
        mic = MICS.get(ch.mic, MICS["ldc_studio"])
        is_di = mic.id == "di"
        ch_dry = _pan_to_stereo(strip, geo["pan"])
        if ch.phase_invert:                 # полярность близкого микрофона; комната слышит источник как есть
            ch_dry = -ch_dry
        mono = dsp.to_mono(strip)

        ch_room = None
        if room_lin > 0 and not is_di:
            tick(base + 0.2 / len(chans), f"Комнатные микрофоны: {ch.name}")
            ch_room = np.zeros((2, n))
            for k, cap in enumerate(pair):
                fir = spatial_fir(scene, (ch.x, ch.y), cap["pos"], sr, rt60, ref, align_samples=align,
                                  pattern=cap["pattern"], axis_deg=cap["axis_deg"])
                ch_room[k] = oaconvolve(mono, fir)[:n]
            ch_room = dsp.air_absorption(ch_room, sr, geo["distance_m"]) * room_lin

        # Диффузное поле: энергия хвоста ∝ (r / rc)²
        ree = 1.0 if is_di else PATTERNS[mic.pattern]["ree"]
        close_amt = (max(ch.mic_distance_cm, 1.0) / 100.0) / rc * math.sqrt(ree)
        if is_di:
            close_amt = 0.25 / max(rc, 0.25)       # «плита» для линейных источников
        # Пара стоит на ref от сцены; физически хвост/прямой = ref/rc. Ограничиваем 3·rc, чтобы
        # в арене/соборе по умолчанию не получалась «каша» (дальше — ручкой Room mics и Reverb send).
        # Направленная пара (X-Y, ORTF…) принимает меньше диффузного поля: × sqrt(REE).
        room_amt = room_lin * min(ref, 3.0 * rc) / rc * math.sqrt(pair_ree) if not is_di else 0.0
        send_gain = (close_amt + room_amt) * dsp.db_to_gain(ch.reverb_send_db)
        if tail is not None:
            send[:n] += mono * send_gain

        dry[:, :n] += ch_dry
        if ch_room is not None:
            room[:, :n] += ch_room
        if dsend is not None and ch.delay_send_db > -59.9:
            dsend[:, :n] += ch_dry * dsp.db_to_gain(ch.delay_send_db)

        if export_stems_dir:
            stem = ch_dry + (ch_room if ch_room is not None else 0.0)
            stems_out[ch.id] = (ch.name, stem, mono * send_gain if tail is not None else None)
        if meters:
            ch_meters[ch.id] = _meter(ch_dry + (ch_room if ch_room is not None else 0.0), sr)

        ch_reports.append({
            "id": ch.id, "name": ch.name, "mic": info.get("mic"), "distance_m": round(geo["distance_m"], 2),
            "delay_ms": round(geo["delay_ms"], 1), "pan": round(geo["pan"], 2),
            "proximity_db": info.get("proximity_db", 0.0), "polar_gain_db": info.get("polar_gain_db", 0.0),
            "reverb_send": round(send_gain, 3), "room": ch_room is not None,
            "peak_db": round(dsp.peak_db(ch_dry), 1),
        })

    tick(0.72, "Хвост помещения")
    rev = np.zeros((2, total))
    if tail is not None and np.any(send):
        for k in range(2):
            rev[k] = oaconvolve(send, tail[k])[:total]
        # ВЧ хвоста гасим воздухом на типичной дистанции
        rev = dsp.air_absorption(rev, sr, ref * 2)
        if abs(rec.reverb_return_db) > 1e-6:
            rev = rev * dsp.db_to_gain(rec.reverb_return_db)

    mix = dry + room + rev
    if dsend is not None and np.any(dsend):
        tick(0.75, "Дилей")
        ir_l, ir_r = d_ir
        if rec.delay_pingpong:
            mono_send = (dsend[0] + dsend[1]) / 2
            dl = oaconvolve(mono_send, ir_l)[:total]
            dr = oaconvolve(mono_send, ir_r)[:total]
        else:
            dl = oaconvolve(dsend[0], ir_l)[:total]
            dr = oaconvolve(dsend[1], ir_r)[:total]
        mix = mix + np.vstack([dl, dr]) * dsp.db_to_gain(rec.delay_return_db)
    amb_report = None
    if scene.ambience != "none":
        tick(0.78, "Эмбиент помещения")
        dry_rms = math.sqrt(float(np.mean(np.square(dry[:, :n])))) + 1e-12
        amb_db = scene.ambience_db + session.ambience_db_offset
        amb = ambience(scene.ambience, total, sr, seed=rec.seed) * dry_rms * dsp.db_to_gain(amb_db)
        mix = mix + amb
        amb_report = round(amb_db, 1)

    if export_stems_dir:
        sd = Path(export_stems_dir)
        sd.mkdir(parents=True, exist_ok=True)
        for cid, (name, stem, stem_send) in stems_out.items():
            full = np.zeros((2, total))
            full[:, :n] = stem
            if stem_send is not None and tail is not None:
                for k in range(2):
                    full[k] += oaconvolve(np.pad(stem_send, (0, total - n)), tail[k])[:total]
            safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip() or cid
            write_audio(sd / f"{safe}.wav", full, sr, bit_depth=32, fmt="wav")

    tick(0.82, "Мастер-шина")
    report_master = {}
    if rec.stereo_width != 1.0:
        mid = (mix[0] + mix[1]) / 2
        side = (mix[0] - mix[1]) / 2 * rec.stereo_width
        mix = np.vstack([mid + side, mid - side])
    if master:
        if rec.master_eq_on:
            mbands = []
            if rec.master_hpf_hz >= 15:
                mbands.append(("highpass", rec.master_hpf_hz, 0.0, 0.707))
            if abs(rec.master_low_db) > 0.05:
                mbands.append(("lowshelf", rec.master_low_freq, rec.master_low_db, 0.7))
            if abs(rec.master_mid_db) > 0.05:
                mbands.append(("peak", rec.master_mid_freq, rec.master_mid_db, max(rec.master_mid_q, 0.1)))
            if abs(rec.master_high_db) > 0.05:
                mbands.append(("highshelf", rec.master_high_freq, rec.master_high_db, 0.7))
            if mbands:
                mix = dsp.apply_eq(mix, sr, mbands)
        if rec.bus_comp_mode == "manual":
            if rec.bus_ratio > 1.0:
                mix = dsp.compressor(mix, sr, threshold_db=rec.bus_threshold_db, ratio=rec.bus_ratio,
                                     attack_ms=max(rec.bus_attack_ms, 0.1), release_ms=max(rec.bus_release_ms, 1.0),
                                     knee_db=8.0, makeup_db=rec.bus_makeup_db)
        elif rec.bus_comp > 0.01:
            mix = dsp.compressor(mix, sr, threshold_db=-14.0 - 8.0 * rec.bus_comp,
                                 ratio=1.3 + 2.2 * rec.bus_comp, attack_ms=30.0, release_ms=250.0,
                                 knee_db=8.0)
        if rec.tape != "off":
            tick(0.86, "Лента")
            mix = dsp.tape(mix, sr, rec.tape, seed=rec.seed)
        tick(0.9, "Громкость и лимитер")
        if rec.normalize:
            mix, report_master = normalize_loudness(mix, sr, rec.target_lufs, rec.ceiling_db, rec.limiter)
            if not rec.limiter:
                mix = np.clip(mix, -1.0, 1.0)
        else:
            before = integrated_lufs(mix, sr)
            mix = limiter(mix, sr, ceiling_db=rec.ceiling_db - 0.3) if rec.limiter else np.clip(mix, -1.0, 1.0)
            report_master = {"lufs_before": round(before, 2), "lufs_after": round(integrated_lufs(mix, sr), 2),
                             "gain_db": 0.0, "true_peak_db": round(true_peak_db(mix), 2)}
    else:
        peak = float(np.max(np.abs(mix))) + 1e-12
        if peak > 0.98:
            mix = mix * (0.98 / peak)
    if duration_s is None and rec.fade_in_s > 0:
        mix = dsp.fade(mix, sr, rec.fade_in_s, 0.0)
    if rec.fade_out_s > 0 and duration_s is None:
        mix = dsp.fade(mix, sr, 0.0, rec.fade_out_s)
    elif tail_len_pad > 0:
        mix = dsp.fade(mix, sr, 0.0, min(tail_len_pad / sr, 1.0))

    path = None
    if out_path:
        tick(0.95, "Запись файла")
        out = dsp.tpdf_dither(mix, rec.bit_depth, seed=rec.seed) \
            if rec.bit_depth < 32 and rec.dither != "off" else mix
        meta = {"title": session.meta.get("title") or session.name, "artist": session.meta.get("artist", ""),
                "album": session.meta.get("album", ""), "date": session.meta.get("year", ""),
                "genre": session.meta.get("genre", ""),
                "comment": session.meta.get("comment") or f"AI Music Studio · {scene.name}"}
        path = write_audio(out_path, out, sr, rec.bit_depth, rec.output_format, metadata=meta,
                           cover=session.meta.get("cover"), bitrate_kbps=rec.mp3_bitrate)

    report = {
        "scene": describe_scene(session),
        "channels": ch_reports,
        "ambience_db": amb_report,
        "duration_s": round(mix.shape[1] / sr, 2),
        "start_s": round(float(start_s), 3),
        "sample_rate": sr,
        "master": report_master or {"lufs": round(integrated_lufs(mix, sr), 2),
                                    "true_peak_db": round(true_peak_db(mix), 2)},
        "render_time_s": round(time.time() - t0, 2),
    }
    if meters:
        report["meters"] = {"hop_s": 0.05, "channels": ch_meters, "master": _meter(mix, sr)}
    tick(1.0, "Готово")
    return RenderResult(audio=mix, sr=sr, report=report, path=path,
                        stems={k: v[0] for k, v in stems_out.items()})


def render_preview(session: Session, start_s: float = 0.0, duration_s: float = 20.0, progress=None,
                   cancel=None, meters: bool = False) -> RenderResult:
    """Короткий фрагмент на 44.1 кГц для прослушивания настроек."""
    return render_session(session, start_s=start_s, duration_s=duration_s,
                          sample_rate=min(session.recording.sample_rate, 44100),
                          progress=progress, cancel=cancel, meters=meters)
