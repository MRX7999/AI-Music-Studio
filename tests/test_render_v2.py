"""Session v2: the full channel strip, room-pair techniques, delay bus, master section."""
import json

import numpy as np
import pytest
import soundfile as sf

from studio import dsp
from studio.audio_io import have_ffmpeg
from studio.generators import DemoGenerator, GenerationRequest
from studio.loudness import integrated_lufs
from studio.render import channel_eq_bands, render_preview, render_session
from studio.scenes import ROOM_TECHNIQUES, SCENES, room_pair, spatial_fir
from studio.session import SESSION_VERSION, Channel, Recording, Session, session_from_stems


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo2")
    return DemoGenerator().generate(GenerationRequest(title="V2", duration=12, bpm=110, key="A minor", seed=3), out)[0]


def stems_of(t):
    return {k: str(v) for k, v in t.stems.items()}


def test_v1_session_file_still_loads(demo, tmp_path):
    s = session_from_stems(stems_of(demo), "old", "studio_a")
    d = s.to_dict()
    # emulate a v1 file: drop every v2 field
    v2_channel = {f for f in Channel.__dataclass_fields__} - {
        "name", "source", "instrument", "id", "color", "mic", "mic_distance_cm", "mic_angle_deg", "x", "y",
        "gain_db", "pan", "stereo", "mute", "solo", "hpf_hz", "eq_low_db", "eq_mid_db", "eq_mid_freq",
        "eq_high_db", "comp", "drive_db", "reverb_send_db"}
    for c in d["channels"]:
        for k in v2_channel:
            c.pop(k)
    for k in ("room_technique", "predelay_ms", "master_eq_on", "bus_comp_mode", "normalize", "dither"):
        d["recording"].pop(k)
    for k in ("room_width", "room_depth", "room_height", "hf_damping", "ambience_kind"):
        d.pop(k)
    d["version"] = 1
    d["recording"]["future_field"] = 123          # unknown fields are ignored
    p = tmp_path / "old.studio.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    s2 = Session.load(p)
    assert s2.version == SESSION_VERSION
    assert s2.channels[0].comp_mode == "auto" and s2.recording.room_technique == "ab"
    r = render_preview(s2, 0, 3)
    assert np.isfinite(r.audio).all()


def test_defaults_keep_v1_eq_bands():
    ch = Channel(name="a", source="x", hpf_hz=80, eq_low_db=2, eq_mid_db=-3, eq_mid_freq=500, eq_high_db=1)
    assert channel_eq_bands(ch) == [("highpass", 80, 0.0, 0.707), ("lowshelf", 100.0, 2, 0.7),
                                    ("peak", 500, -3, 1.0), ("highshelf", 10000.0, 1, 0.7)]
    ch.eq_on = False
    ch.lpf_hz = 8000
    assert channel_eq_bands(ch) == [("highpass", 80, 0.0, 0.707), ("lowpass", 8000, 0.0, 0.707)]


def test_phase_invert_flips_close_mic(demo):
    s = session_from_stems({"bass": stems_of(demo)["bass"]}, "p", "dry")
    s.recording.bus_comp = 0.0
    a = render_preview(s, 0, 4).audio
    s.channels[0].phase_invert = True
    b = render_preview(s, 0, 4).audio
    assert np.allclose(a, -b, atol=1e-6)


def test_manual_compressor_squeezes_dynamics(tmp_path):
    sr = 48000
    t = np.arange(4 * sr) / sr
    level = np.where((t % 1.0) < 0.5, 0.5, 0.03)            # −6 dB / −30 dB секции
    sf.write(str(tmp_path / "keys.wav"), (level * np.sin(2 * np.pi * 330 * t)).astype(np.float32), sr)
    s = session_from_stems({"keys": str(tmp_path / "keys.wav")}, "c", "dry")
    s.recording.bus_comp = 0.0
    s.recording.normalize = False
    ch = s.channels[0]
    ch.comp = 0.0

    def spread():
        r = render_preview(s, 0, 4)
        y, rs = r.audio, r.sr
        loud = dsp.rms_db(y[:, int(1.1 * rs):int(1.4 * rs)])
        quiet = dsp.rms_db(y[:, int(1.6 * rs):int(1.9 * rs)])
        return loud - quiet
    loose = spread()
    ch.comp_mode = "manual"
    ch.comp_threshold_db, ch.comp_ratio, ch.comp_attack_ms, ch.comp_makeup_db = -40.0, 8.0, 1.0, 0.0
    tight = spread()
    assert loose > 18 and tight < loose - 12


def test_compressor_catches_transient_after_silence():
    sr = 48000
    x = np.zeros(sr)
    x[sr // 2:] = 0.5 * np.sin(2 * np.pi * 200 * np.arange(sr // 2) / sr)
    y = dsp.compressor(x, sr, threshold_db=-30, ratio=10, attack_ms=1, release_ms=100, makeup_db=0)
    seg = slice(sr // 2 + int(0.004 * sr), sr // 2 + int(0.010 * sr))
    assert dsp.peak_db(y[:, seg]) < dsp.peak_db(x[np.newaxis, seg]) - 15


def test_gate_silences_quiet_parts():
    sr = 44100
    t = np.arange(sr) / sr
    x = np.where(t < 0.5, 0.5, 0.001) * np.sin(2 * np.pi * 220 * t)
    y = dsp.gate(x[np.newaxis, :], sr, threshold_db=-30, range_db=40)
    assert dsp.rms_db(y[:, int(0.7 * sr):]) < dsp.rms_db(x[np.newaxis, int(0.7 * sr):]) - 20


def test_delay_ir_echo_times_and_levels():
    sr = 48000
    left, right = dsp.delay_ir(sr, 250, 0.5, hicut_hz=sr, pingpong=True)
    d = int(sr * 0.25)
    assert left[d] == pytest.approx(1.0) and right[d] == 0.0
    assert right[2 * d] == pytest.approx(0.5) and left[3 * d] == pytest.approx(0.25)
    mono_l, mono_r = dsp.delay_ir(sr, 250, 0.5, hicut_hz=sr, pingpong=False)
    assert np.array_equal(mono_l, mono_r)


def test_delay_send_adds_echoes(demo):
    s = session_from_stems({"lead": stems_of(demo)["lead"]}, "d", "dry")
    s.recording.normalize = False
    s.recording.bus_comp = 0.0
    base = render_preview(s, 0, 6).audio
    s.channels[0].delay_send_db = 0.0
    s.recording.delay_time_ms = 300
    wet = render_preview(s, 0, 6).audio
    assert dsp.rms_db(wet) > dsp.rms_db(base) + 0.5


def test_room_techniques_change_the_pair(demo):
    st = stems_of(demo)
    outs = {}
    for tech in ROOM_TECHNIQUES:
        s = session_from_stems(st, "t", "live_room")
        s.recording.room_technique = tech
        s.recording.room_mics_db = 0.0
        outs[tech] = render_preview(s, 0, 4).audio
    assert not np.allclose(outs["ab"], outs["xy"])
    assert not np.allclose(outs["ortf"], outs["blumlein"])
    caps = room_pair(5, 8, "ortf", 0.6, 2.2)
    assert caps[1]["pos"][0] - caps[0]["pos"][0] == pytest.approx(0.17)
    assert caps[0]["axis_deg"] == -55 and caps[0]["pattern"] == "cardioid"


def test_directional_capsule_rejects_rear_source():
    sc = SCENES["dry"]
    front = spatial_fir(sc, (5, 2), (5, 6, 2.2), 48000, 0.0, 4.0, pattern="cardioid", axis_deg=0)
    back = spatial_fir(sc, (5, 2), (5, 6, 2.2), 48000, 0.0, 4.0, pattern="cardioid", axis_deg=180)
    assert front.max() > 5 * back.max()


def test_custom_room_size_rescales_layout(demo):
    s = session_from_stems(stems_of(demo), "r", "studio_a")
    ch = s.channels[0]
    fx = ch.x / s.scene_preset.width
    rc0 = render_preview(s, 0, 2).report["scene"]["critical_distance_m"]
    s.set_room_size(18, 14, 6)
    assert s.scene_preset.width == 18 and s.scene_preset.height == 6
    assert ch.x / 18 == pytest.approx(fx, abs=0.02)
    rc1 = render_preview(s, 0, 2).report["scene"]["critical_distance_m"]
    assert rc1 > rc0
    s.set_scene("club")
    assert s.room_width is None and s.scene_preset.width == SCENES["club"].width


def test_master_eq_and_no_normalize(demo):
    s = session_from_stems(stems_of(demo), "m", "studio_a")
    s.recording.normalize = False
    r0 = render_preview(s, 0, 6)
    assert r0.report["master"]["gain_db"] == 0.0
    s.recording.master_high_db, s.recording.master_high_freq = 9.0, 4000.0

    def hf(x, sr):
        return dsp.rms_db(dsp.apply_eq(x, sr, [("highpass", 5000, 0, 0.707)]))
    r1 = render_preview(s, 0, 6)
    assert hf(r1.audio, r1.sr) > hf(r0.audio, r0.sr) + 3


def test_fades_meters_and_metadata(demo, tmp_path):
    s = session_from_stems(stems_of(demo), "f", "studio_a")
    s.recording.fade_in_s = 1.0
    s.recording.bit_depth = 16
    s.meta.update({"artist": "Tester", "album": "Album"})
    r = render_session(s, out_path=tmp_path / "mix", sample_rate=44100, meters=True)
    a, sr = sf.read(str(r.path))
    assert np.max(np.abs(a[: int(0.02 * sr)])) < 0.01
    m = r.report["meters"]
    assert set(m["channels"]) == {c.id for c in s.channels} and len(m["master"]["peak"]) > 10
    assert abs(integrated_lufs(a.T, sr) - s.recording.target_lufs) < 1.5


@pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg not installed")
def test_mp3_bitrate(demo, tmp_path):
    s = session_from_stems(stems_of(demo), "b", "dry")
    s.recording.output_format = "mp3"
    sizes = {}
    for kbps in (128, 320):
        s.recording.mp3_bitrate = kbps
        sizes[kbps] = render_session(s, out_path=tmp_path / f"m{kbps}", sample_rate=44100).path.stat().st_size
    assert sizes[128] < sizes[320] * 0.6


def test_recording_defaults_are_neutral():
    r = Recording()
    assert (r.room_technique, r.predelay_ms, r.reverb_return_db, r.master_eq_on, r.bus_comp_mode,
            r.normalize, r.fade_in_s, r.tail_s, r.dither) == ("ab", 0.0, 0.0, True, "auto", True, 0.0, 1.5, "tpdf")
