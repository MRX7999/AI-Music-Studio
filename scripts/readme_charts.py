"""Charts for the README, computed by the real engine (no hand-drawn data).

    pip install matplotlib==3.9.2
    python scripts/readme_charts.py --out docs/charts

Inputs are two songs from the offline demo synthesizer (seeded, so the charts are reproducible):
the bandwidth chart cuts the first one at 11 kHz like a 128 kbps MP3 and runs the built-in
extension; the reference chart matches it to the second one, mastered to −11 LUFS, with the
built-in matcher; the room
chart comes straight from the scene presets; the workflow and architecture diagrams are drawn
with the same palette as the app.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from scipy.signal import welch  # noqa: E402

from studio import refmaster, superres  # noqa: E402
from studio.audio_io import read_audio, write_audio  # noqa: E402
from studio.generators.base import GenerationRequest  # noqa: E402
from studio.generators.demo import DemoGenerator  # noqa: E402
from studio.loudness import integrated_lufs, normalize_loudness  # noqa: E402
from studio.scenes import SCENES  # noqa: E402

BG0, BG1, STROKE = "#0F1014", "#15171C", "#2A2E38"
TEXT, TEXT2, TEXT3 = "#E7E9EE", "#A2A9B6", "#6E7584"
AMBER, TEAL, GREEN, YELLOW, PINK = "#FF9F43", "#4FD1C5", "#4ADE80", "#FACC15", "#F472B6"

ROOM_EN = {"dry": "Dry", "booth": "Vocal booth", "studio_a": "Studio A", "live_room": "Live room",
           "garage": "Garage", "club": "Club (300)", "concert_hall": "Concert hall", "cathedral": "Cathedral",
           "arena": "Arena", "open_air": "Open air"}


def style():
    plt.rcParams.update({
        "figure.facecolor": BG0, "axes.facecolor": BG1, "axes.edgecolor": STROKE, "axes.labelcolor": TEXT2,
        "axes.titlecolor": TEXT, "axes.titleweight": "semibold", "axes.titlesize": 13, "axes.titlelocation": "left",
        "axes.titlepad": 12, "xtick.color": TEXT3, "ytick.color": TEXT3, "grid.color": STROKE, "grid.linewidth": 0.6,
        "text.color": TEXT, "font.size": 10, "legend.frameon": False, "legend.labelcolor": TEXT2,
        "savefig.facecolor": BG0, "axes.spines.top": False, "axes.spines.right": False,
    })


def spectrum_db(x: np.ndarray, sr: int):
    f, p = welch(x.mean(axis=0), sr, nperseg=8192)
    return f, 10 * np.log10(p + 1e-14)


def third_octave(f, db):
    out = np.empty_like(db)
    k = 2 ** (1 / 6)
    for i, fi in enumerate(f):
        m = (f >= fi / k) & (f <= fi * k)
        out[i] = db[m].mean() if m.any() else db[i]
    return out


def song(gen: DemoGenerator, out: Path, title: str, style_: str, seed: int, bpm: int) -> Path:
    req = GenerationRequest(title=title, style=style_, duration=30, seed=seed, bpm=bpm, instrumental=True)
    return Path(gen.generate(req, out)[0].path)


def chart_bandwidth(src: Path, work: Path, dst: Path):
    a, sr = read_audio(src)
    X = np.fft.rfft(a, axis=1)
    f = np.fft.rfftfreq(a.shape[1], 1 / sr)
    X[:, f > 11000] = 0
    cut = np.fft.irfft(X, a.shape[1], axis=1)
    write_audio(work / "cut.wav", cut, sr, 24)
    rep = superres.upscale(work / "cut.wav", work / "ext.wav", 48000, backend="builtin")
    ext, esr = read_audio(rep["output"])
    full48 = superres._resample(a, sr, 48000)
    cut48 = superres._resample(cut, sr, 48000)

    fig, ax = plt.subplots(figsize=(10, 4.2), dpi=160)
    for x, lab, col, lw in [(full48, "Original (full band)", TEXT3, 1.2), (cut48, "MP3-like source, cut at 11 kHz", AMBER, 1.6),
                            (ext, "After the built-in extension (no model)", TEAL, 1.8)]:
        fx, d = spectrum_db(x, 48000)
        d = third_octave(fx, d)
        m = (fx >= 200) & (fx <= 23500)
        ax.semilogx(fx[m], d[m], color=col, lw=lw, label=lab)
    ax.axvline(rep["cutoff_before_hz"], color=AMBER, ls="--", lw=0.8, alpha=0.7)
    ax.text(rep["cutoff_before_hz"] * 1.03, ax.get_ylim()[1] - 6, f"detected cutoff {rep['cutoff_before_hz'] / 1000:.1f} kHz",
            color=AMBER, fontsize=9)
    ax.set_xlim(200, 24000)
    ax.set_xticks([250, 500, 1000, 2000, 4000, 8000, 16000])
    ax.set_xticklabels(["250", "500", "1k", "2k", "4k", "8k", "16k"])
    ax.set_xlabel("Frequency, Hz")
    ax.set_ylabel("Level, dB (1/3-octave)")
    ax.grid(True, which="major")
    ax.set_title("Bandwidth restore without a model: the missing octave comes back above the cutoff")
    ax.legend(loc="lower left")
    fig.tight_layout()
    fig.savefig(dst)
    plt.close(fig)
    return rep


def chart_reference(mix: Path, ref_song: Path, work: Path, dst: Path):
    rb, rbsr = read_audio(ref_song)                     # a commercial-style reference: another song mastered loud
    rb, _ = normalize_loudness(rb, rbsr, target_lufs=-11.0, ceiling_db=-1.0)
    ref = write_audio(work / "reference.wav", rb, rbsr, 24)
    rep = refmaster.master(mix, ref, work / "matched.wav", backend="builtin", max_db=6.0)
    a, sr = read_audio(mix)
    r, rsr = read_audio(ref)
    y, _ = read_audio(rep["output"])
    fe, g = refmaster.eq_curve(a, r, sr, max_db=6.0)

    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(11, 4.2), dpi=160, gridspec_kw={"width_ratios": [2.2, 1]})
    for x, s_, lab, col, lw in [(a, sr, "Your mix", AMBER, 1.5), (r, rsr, "Reference", TEXT3, 1.3), (y, sr, "Matched", TEAL, 1.8)]:
        fx, d = spectrum_db(x, s_)
        d = third_octave(fx, d)
        mid = (fx >= 100) & (fx <= 8000)
        d = d - d[mid].mean()
        m = (fx >= 40) & (fx <= 18000)
        ax.semilogx(fx[m], d[m], color=col, lw=lw, label=lab)
    m = (fe >= 40) & (fe <= 18000)
    axr = ax.twinx()
    axr.fill_between(fe[m], 0, g[m], color=PINK, alpha=0.18, lw=0)
    axr.semilogx(fe[m], g[m], color=PINK, lw=1.0, label="EQ applied")
    axr.set_ylim(-14, 14)
    axr.set_ylabel("EQ, dB", color=PINK)
    axr.tick_params(colors=PINK)
    axr.spines["right"].set_visible(True)
    axr.spines["right"].set_color(STROKE)
    ax.set_xticks([50, 100, 250, 500, 1000, 2000, 4000, 8000, 16000])
    ax.set_xticklabels(["50", "100", "250", "500", "1k", "2k", "4k", "8k", "16k"])
    ax.set_xlabel("Frequency, Hz")
    ax.set_ylabel("Tonal balance, dB")
    ax.grid(True)
    ax.set_title("Reference mastering: tone and loudness move toward the reference")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = axr.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="lower left")

    vals = [integrated_lufs(a, sr), integrated_lufs(r, rsr), integrated_lufs(y, sr)]
    names = ["Your mix", "Reference", "Matched"]
    yy = np.arange(3)[::-1]
    ax2.barh(yy, [v + 30 for v in vals], left=-30, color=[AMBER, TEXT3, TEAL], height=0.55)
    for yi, v in zip(yy, vals):
        ax2.text(v + 0.4, yi, f"{v:.1f}", va="center", color=TEXT, fontsize=10, fontweight="semibold")
    ax2.set_yticks(yy)
    ax2.set_yticklabels(names)
    ax2.set_xlim(-30, -4)
    ax2.set_xlabel("Integrated loudness, LUFS")
    ax2.set_title("Loudness (BS.1770)")
    ax2.grid(True, axis="x")
    fig.tight_layout()
    fig.savefig(dst)
    plt.close(fig)
    return rep


def chart_rooms(dst: Path):
    ids = [k for k in SCENES if SCENES[k].rt60 > 0]
    ids.sort(key=lambda k: SCENES[k].rt60)
    lo = [SCENES[k].rt60 * SCENES[k].lf_ratio for k in ids]
    mid = [SCENES[k].rt60 for k in ids]
    hi = [SCENES[k].rt60 * SCENES[k].hf_ratio for k in ids]
    y = np.arange(len(ids))
    fig, ax = plt.subplots(figsize=(10, 4.4), dpi=160)
    h = 0.26
    ax.barh(y - h, lo, h, color=AMBER, label="Lows (125 Hz)")
    ax.barh(y, mid, h, color=TEAL, label="Mids (1 kHz)")
    ax.barh(y + h, hi, h, color=YELLOW, label="Highs (8 kHz)")
    for i, k in enumerate(ids):
        s = SCENES[k]
        ax.text(max(lo[i], mid[i]) + 0.08, y[i], f"{s.width:g}×{s.depth:g}×{s.height:g} m", va="center",
                color=TEXT3, fontsize=8.5)
    ax.set_yticks(y)
    ax.set_yticklabels([ROOM_EN.get(k, k) for k in ids])
    ax.set_xlabel("Reverb time RT60, seconds")
    ax.set_xlim(0, max(lo) + 1.4)
    ax.grid(True, axis="x")
    ax.set_title("Nine rooms (plus Dry): size and frequency-dependent decay")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(dst)
    plt.close(fig)


def _box(ax, x, y, w, h, title, lines, color, title_size=12.5, line_size=9.5):
    from matplotlib.patches import FancyBboxPatch
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.18", fc=BG1, ec=color, lw=1.6))
    ax.plot([x + 0.22, x + 0.82], [y + h - 0.16, y + h - 0.16], color=color, lw=3.2, solid_capstyle="round")
    ax.text(x + 0.22, y + h - 0.46, title, color=TEXT, fontsize=title_size, fontweight="bold", va="center")
    for i, ln in enumerate(lines):
        ax.text(x + 0.22, y + h - 0.9 - i * 0.36, ln, color=TEXT2, fontsize=line_size, va="center")


def _arrow(ax, x0, y0, x1, y1, color=TEXT3, label="", dy=0.18, both=False):
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                arrowprops=dict(arrowstyle="<|-|>" if both else "-|>", color=color, lw=1.4, mutation_scale=14))
    if label:
        ax.text((x0 + x1) / 2, (y0 + y1) / 2 + dy, label, color=color, fontsize=8.5, ha="center", va="bottom",
                linespacing=1.3)


def diagram_workflow(dst: Path):
    steps = [("1  Generate", ["ACE-Step 1.5 (local)", "Suno via GPTunneL", "offline demo synth"], AMBER),
             ("2  Stage", ["10 rooms: booth → arena", "12 microphone models", "drag players and mics"], TEAL),
             ("3  Record + edit", ["vocal takes on the mix", "optional RVC voice", "regenerate a section"], PINK),
             ("4  Mix + master", ["EQ, comp, sends", "tape, width", "LUFS + true peak"], YELLOW),
             ("5  Release", ["bandwidth restore", "reference mastering", "cover, LRC, AI check"], GREEN),
             ("6  Publish", ["Telegram, YouTube", "distributor package", "after you confirm"], "#8AB4FF")]
    w, h, gap = 2.7, 2.0, 0.42
    fig, ax = plt.subplots(figsize=(17, 3.0), dpi=150)
    ax.set_xlim(-0.1, len(steps) * (w + gap) - gap + 0.1)
    ax.set_ylim(-0.15, h + 0.15)
    ax.axis("off")
    for i, (t, lines, c) in enumerate(steps):
        x = i * (w + gap)
        _box(ax, x, 0, w, h, t, lines, c)
        if i < len(steps) - 1:
            _arrow(ax, x + w + 0.04, h / 2, x + w + gap - 0.04, h / 2)
    fig.savefig(dst, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)


def diagram_architecture(dst: Path):
    fig, ax = plt.subplots(figsize=(16, 5.6), dpi=150)
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 5.6)
    ax.axis("off")
    _box(ax, 0.1, 0.9, 4.0, 4.3, "SwiftUI app", ["Generate · Stage · Mixer · Master", "Release · Record · Regenerate",
                                                  "AVAudioEngine playback, meters", "Core Audio input, take writer",
                                                  "Keychain for every key", "Settings: AI Models, Publishing",
                                                  "--selftest, --screenshots"], AMBER)
    _box(ax, 5.8, 0.9, 4.4, 4.3, "Python engine (local process)", ["render: rooms, mics, console, master",
                                                                    "generators: acestep, gptunnel, demo",
                                                                    "superres · refmaster · lyrics · cover",
                                                                    "detect: fakeprint built in (NumPy)",
                                                                    "editing: splice, bit-exact outside region",
                                                                    "publish: release folders, queue, retry",
                                                                    "tools.py: MLX → PyTorch → built-in"], TEAL)
    _box(ax, 12.0, 2.95, 3.9, 2.25, "Local tools (optional)", ["FlashSR · mlx-whisper · demucs-mlx",
                                                               "mflux Z-Image · aigm · mlx-rvc",
                                                               "Matchering (GPLv3, own venv)"], GREEN, line_size=9)
    _box(ax, 12.0, 0.2, 3.9, 2.25, "Network (opt-in)", ["GPTunneL (Suno) · remote ACE-Step",
                                                        "Telegram · YouTube",
                                                        "Sightengine · ACRCloud"], PINK, line_size=9)
    _arrow(ax, 4.15, 3.05, 5.75, 3.05, AMBER, "JSON lines\nstdin / stdout", both=True)
    ax.text(4.95, 2.85, "progress, cancel", color=TEXT3, fontsize=8, ha="center", va="top")
    _arrow(ax, 10.25, 4.05, 11.95, 4.05, GREEN, "subprocess\nfiles in / out")
    _arrow(ax, 10.25, 1.35, 11.95, 1.35, PINK, "HTTPS\nkeys from Keychain")
    ax.text(8.2, 0.45, "nothing leaves the Mac unless you choose a cloud service or press Publish",
            color=TEXT3, fontsize=9, ha="center")
    fig.savefig(dst, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "charts"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    style()
    gen = DemoGenerator()
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        a = song(gen, work / "a", "Night Drive", "synthwave, warm pads", 3, 100)
        b = song(gen, work / "b", "Bright Ref", "pop, bright, punchy", 11, 124)
        r1 = chart_bandwidth(a, work, out / "bandwidth.png")
        r2 = chart_reference(a, b, work, out / "reference.png")
    chart_rooms(out / "rooms.png")
    diagram_workflow(out / "workflow.png")
    diagram_architecture(out / "architecture.png")
    print(f"bandwidth: {r1['cutoff_before_hz']:.0f} → {r1['cutoff_after_hz']:.0f} Hz")
    print(f"reference: {r2['lufs_before']} → {r2['lufs_after']} LUFS (ref {r2['reference_lufs']}), EQ {r2['eq_db']}")
    print("written to", out)


if __name__ == "__main__":
    main()
