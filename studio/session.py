"""Модель сессии виртуальной студии и её JSON-сериализация (*.studio.json)."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .scenes import SCENES, ScenePreset

SESSION_VERSION = 1


@dataclass
class InstrumentPreset:
    id: str
    name: str
    mic: str
    distance_cm: float
    angle_deg: float
    stage_pos: tuple          # доли сцены (fx, fy): 0..1 по ширине и глубине сцены
    color: str
    stereo: bool = False      # сохранять стерео исходника (пэды, клавиши, микс)
    hpf_hz: float = 30.0
    comp: float = 0.3
    eq: tuple = (0.0, 0.0, 1000.0, 0.0)   # low, mid, mid_freq, high (дБ)
    reverb_send_db: float = 0.0


INSTRUMENTS: dict[str, InstrumentPreset] = {i.id: i for i in [
    InstrumentPreset("vocals", "Вокал", "ldc_studio", 15, 0, (0.5, 0.85), "#f5c2e7", hpf_hz=80, comp=0.55,
                     eq=(0.0, -1.0, 350.0, 1.5)),
    InstrumentPreset("backing", "Бэк-вокал", "ldc_bright", 40, 10, (0.72, 0.7), "#f2cdcd", hpf_hz=120, comp=0.5,
                     reverb_send_db=3.0),
    InstrumentPreset("drums", "Ударные", "sdc_pencil", 80, 0, (0.5, 0.2), "#fab387", stereo=True, hpf_hz=35, comp=0.4),
    InstrumentPreset("kick", "Бочка", "dyn_kick", 5, 0, (0.5, 0.25), "#eba0ac", hpf_hz=30, comp=0.5),
    InstrumentPreset("bass", "Бас", "dyn_broadcast", 10, 0, (0.28, 0.25), "#f9e2af", hpf_hz=30, comp=0.6,
                     reverb_send_db=-8.0),
    InstrumentPreset("guitar", "Гитара", "dyn_inst", 5, 20, (0.78, 0.4), "#a6e3a1", hpf_hz=80, comp=0.3),
    InstrumentPreset("acoustic", "Акустическая гитара", "sdc_pencil", 25, 15, (0.25, 0.55), "#94e2d5", hpf_hz=70,
                     comp=0.35),
    InstrumentPreset("piano", "Фортепиано / клавиши", "ldc_studio", 60, 0, (0.12, 0.62), "#89dceb", stereo=True,
                     hpf_hz=40, comp=0.25),
    InstrumentPreset("synth", "Синтезатор / пэд", "di", 0, 0, (0.88, 0.58), "#74c7ec", stereo=True, hpf_hz=40,
                     comp=0.2),
    InstrumentPreset("strings", "Струнные", "ribbon", 150, 0, (0.3, 0.15), "#89b4fa", stereo=True, hpf_hz=50,
                     comp=0.15, reverb_send_db=3.0),
    InstrumentPreset("brass", "Духовые", "ribbon", 60, 0, (0.7, 0.15), "#b4befe", stereo=False, hpf_hz=80,
                     comp=0.3),
    InstrumentPreset("other", "Прочее", "ldc_studio", 50, 0, (0.65, 0.5), "#cba6f7", stereo=True, hpf_hz=40,
                     comp=0.3),
    InstrumentPreset("mix", "Готовый микс", "di", 0, 0, (0.5, 0.5), "#cdd6f4", stereo=True, hpf_hz=20, comp=0.1),
]}

# Имена стемов (Demucs / HPSS / демо-синтезатор) → инструмент
STEM_TO_INSTRUMENT = {
    "vocals": "vocals", "vocal": "vocals", "voice": "vocals", "center": "vocals",
    "drums": "drums", "percussion": "drums", "perc": "drums",
    "kick": "kick",
    "bass": "bass",
    "guitar": "guitar",
    "piano": "piano", "keys": "piano",
    "synth": "synth", "pad": "synth", "lead": "synth",
    "strings": "strings", "brass": "brass",
    "other": "other", "harmony": "other", "sides": "other",
    "mix": "mix", "no_vocals": "other", "instrumental": "other",
}


@dataclass
class Channel:
    name: str
    source: str
    instrument: str = "other"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    color: str = "#cba6f7"
    mic: str = "ldc_studio"
    mic_distance_cm: float = 30.0
    mic_angle_deg: float = 0.0
    x: float = 0.0
    y: float = 0.0
    gain_db: float = 0.0
    pan: float | None = None          # None → авто по положению на сцене
    stereo: bool = False
    mute: bool = False
    solo: bool = False
    hpf_hz: float = 30.0
    eq_low_db: float = 0.0
    eq_mid_db: float = 0.0
    eq_mid_freq: float = 1000.0
    eq_high_db: float = 0.0
    comp: float = 0.3
    drive_db: float = 0.0
    reverb_send_db: float = 0.0


@dataclass
class Recording:
    sample_rate: int = 48000
    bit_depth: int = 24               # 16 / 24 / 32 (float)
    preamp: str = "clean"
    preamp_drive_db: float = 0.0
    tape: str = "off"
    room_mics_db: float = -6.0
    align_room_mics: bool = True
    pair_spacing_m: float = 0.6
    stereo_width: float = 1.0
    bus_comp: float = 0.3
    target_lufs: float = -14.0
    ceiling_db: float = -1.0
    limiter: bool = True
    output_format: str = "wav"        # wav / flac / alac / mp3
    fade_out_s: float = 0.0
    seed: int = 42


@dataclass
class Session:
    name: str = "Новая сессия"
    scene: str = "studio_a"
    rt60_scale: float = 1.0
    ambience_db_offset: float = 0.0
    listener_x: float | None = None
    listener_y: float | None = None
    channels: list = field(default_factory=list)
    recording: Recording = field(default_factory=Recording)
    meta: dict = field(default_factory=dict)   # title, lyrics, cover, engine, prompt…
    version: int = SESSION_VERSION

    # ── сцена ────────────────────────────────────────────────
    @property
    def scene_preset(self) -> ScenePreset:
        return SCENES.get(self.scene, SCENES["studio_a"])

    @property
    def rt60(self) -> float:
        return self.scene_preset.rt60 * self.rt60_scale

    def listener(self) -> tuple[float, float]:
        sc = self.scene_preset
        dx, dy = sc.listener_pos()
        return (self.listener_x if self.listener_x is not None else dx,
                self.listener_y if self.listener_y is not None else dy)

    def set_scene(self, scene_id: str, keep_layout: bool = True) -> None:
        """Меняет помещение, пересчитывая позиции в новые размеры сцены."""
        old = self.scene_preset
        new = SCENES[scene_id]
        ox0, oy0, ox1, oy1 = old.stage_rect()
        nx0, ny0, nx1, ny1 = new.stage_rect()
        for ch in self.channels:
            if keep_layout:
                fx = (ch.x - ox0) / max(ox1 - ox0, 1e-6)
                fy = (ch.y - oy0) / max(oy1 - oy0, 1e-6)
            else:
                fx, fy = INSTRUMENTS.get(ch.instrument, INSTRUMENTS["other"]).stage_pos
            ch.x = nx0 + min(max(fx, -0.2), 1.2) * (nx1 - nx0)
            ch.y = ny0 + min(max(fy, -0.2), 1.2) * (ny1 - ny0)
            ch.x = min(max(ch.x, 0.3), new.width - 0.3)
            ch.y = min(max(ch.y, 0.3), new.depth - 0.3)
        self.scene = scene_id
        self.listener_x = None
        self.listener_y = None

    # ── каналы ───────────────────────────────────────────────
    def add_channel(self, source: str | Path, name: str | None = None, instrument: str | None = None) -> Channel:
        source = str(source)
        stem = Path(source).stem.lower()
        inst_id = instrument or STEM_TO_INSTRUMENT.get(stem, None)
        if inst_id is None:
            inst_id = next((v for k, v in STEM_TO_INSTRUMENT.items() if k in stem), "other")
        preset = INSTRUMENTS.get(inst_id, INSTRUMENTS["other"])
        x0, y0, x1, y1 = self.scene_preset.stage_rect()
        # разводим одинаковые инструменты, чтобы не лежали друг на друге
        same = sum(1 for c in self.channels if c.instrument == inst_id)
        fx = min(max(preset.stage_pos[0] + 0.12 * same * (-1) ** same, 0.05), 0.95)
        ch = Channel(
            name=name or preset.name,
            source=source,
            instrument=inst_id,
            color=preset.color,
            mic=preset.mic,
            mic_distance_cm=preset.distance_cm,
            mic_angle_deg=preset.angle_deg,
            x=x0 + fx * (x1 - x0),
            y=y0 + preset.stage_pos[1] * (y1 - y0),
            stereo=preset.stereo,
            hpf_hz=preset.hpf_hz,
            comp=preset.comp,
            eq_low_db=preset.eq[0], eq_mid_db=preset.eq[1], eq_mid_freq=preset.eq[2], eq_high_db=preset.eq[3],
            reverb_send_db=preset.reverb_send_db,
        )
        if name is None:
            ch.name = preset.name if same == 0 else f"{preset.name} {same + 1}"
        self.channels.append(ch)
        return ch

    def apply_instrument(self, ch: Channel, inst_id: str) -> None:
        p = INSTRUMENTS[inst_id]
        ch.instrument = inst_id
        ch.color = p.color
        ch.mic = p.mic
        ch.mic_distance_cm = p.distance_cm
        ch.mic_angle_deg = p.angle_deg
        ch.stereo = p.stereo
        ch.hpf_hz = p.hpf_hz
        ch.comp = p.comp
        ch.eq_low_db, ch.eq_mid_db, ch.eq_mid_freq, ch.eq_high_db = p.eq
        ch.reverb_send_db = p.reverb_send_db

    def channel(self, ch_id: str) -> Channel | None:
        return next((c for c in self.channels if c.id == ch_id), None)

    # ── JSON ─────────────────────────────────────────────────
    def to_dict(self, base_dir: Path | None = None) -> dict:
        d = asdict(self)
        if base_dir:
            for ch in d["channels"]:
                try:
                    ch["source"] = str(Path(ch["source"]).resolve().relative_to(base_dir.resolve()))
                except ValueError:
                    pass
        return d

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(path.parent), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @classmethod
    def from_dict(cls, d: dict, base_dir: Path | None = None) -> "Session":
        d = dict(d)
        rec = Recording(**{k: v for k, v in d.pop("recording", {}).items() if k in Recording.__dataclass_fields__})
        chans = []
        for c in d.pop("channels", []):
            c = {k: v for k, v in c.items() if k in Channel.__dataclass_fields__}
            if base_dir and not Path(c["source"]).is_absolute():
                c["source"] = str((base_dir / c["source"]).resolve())
            chans.append(Channel(**c))
        fields_ok = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        s = cls(**fields_ok)
        s.channels = chans
        s.recording = rec
        if s.scene not in SCENES:
            s.scene = "studio_a"
        return s

    @classmethod
    def load(cls, path: str | Path) -> "Session":
        path = Path(path)
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")), path.parent)


def session_from_stems(stems: dict, name: str = "Сессия", scene: str = "studio_a", meta: dict | None = None) -> Session:
    """stems: {stem_name: path}. Порядок каналов — как у пульта: вокал → ритм → гармония."""
    order = ["vocals", "backing", "drums", "kick", "bass", "guitar", "acoustic", "piano", "synth",
             "strings", "brass", "other", "mix"]
    s = Session(name=name, scene=scene, meta=dict(meta or {}))

    def rank(item):
        inst = STEM_TO_INSTRUMENT.get(Path(item[1]).stem.lower(), STEM_TO_INSTRUMENT.get(item[0].lower(), "other"))
        return order.index(inst) if inst in order else len(order)

    for stem_name, path in sorted(stems.items(), key=rank):
        inst = STEM_TO_INSTRUMENT.get(stem_name.lower())
        s.add_channel(path, instrument=inst)
    return s
