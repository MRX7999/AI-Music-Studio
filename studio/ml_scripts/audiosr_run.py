"""AudioSR 0.0.7 mono runner (executed with the Python of the `audiosr` uv tool, not the engine).

usage: python audiosr_run.py IN.wav OUT.wav [--steps 12] [--guidance 2.0] [--device auto] [--seed 42]

Loads the model once, processes 10.24 s chunks with 1 s cosine crossfades, writes 48 kHz mono
float WAV. Progress lines "NN%" are parsed by the engine.
"""
import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

CHUNK_SEC = 10.24
OVERLAP_SEC = 1.0
SR_OUT = 48000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--steps", type=int, default=12)
    ap.add_argument("--guidance", type=float, default=2.0)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    data, sr = sf.read(a.input, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    device = a.device
    if device == "auto":
        import torch
        device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
    from audiosr import build_model, super_resolution
    print(f"AudioSR basic on {device}: {mono.size / sr:.1f} s, {a.steps} steps, guidance {a.guidance}", flush=True)
    model = build_model(model_name="basic", device=device)

    chunk, ov = int(CHUNK_SEC * sr), int(OVERLAP_SEC * sr)
    hop = chunk - ov
    out = None
    ov48 = int(OVERLAP_SEC * SR_OUT)
    pos, idx = 0, 0
    with tempfile.TemporaryDirectory() as td:
        while pos < mono.size:
            end = min(pos + chunk, mono.size)
            tmp = Path(td) / f"c{idx}.wav"
            sf.write(str(tmp), mono[pos:end], sr, subtype="FLOAT")
            y = super_resolution(model, str(tmp), seed=a.seed + idx, ddim_steps=a.steps,
                                 guidance_scale=a.guidance, latent_t_per_second=12.8)
            y = y.squeeze().cpu().numpy() if hasattr(y, "cpu") else np.asarray(y).squeeze()
            y = y[: int(round((end - pos) * SR_OUT / sr))]
            if out is None:
                out = y
            else:
                n = min(ov48, out.size, y.size)
                t = np.linspace(0, np.pi, n)
                out[-n:] = out[-n:] * (1 + np.cos(t)) / 2 + y[:n] * (1 - np.cos(t)) / 2
                out = np.concatenate([out, y[n:]])
            idx += 1
            print(f"{end / mono.size * 100:.0f}%", flush=True)
            if end >= mono.size:
                break
            pos += hop
    sf.write(a.output, out.astype(np.float32), SR_OUT, subtype="FLOAT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
