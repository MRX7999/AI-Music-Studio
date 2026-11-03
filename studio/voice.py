"""Voice conversion of a recorded take (RVC). MLX port first, any other RVC CLI via a template.

The default template targets `mlx-rvc convert IN OUT --model MODEL.pth --pitch N --f0-method rmvpe`.
For W-Okada VCClient or rvc-python set your own template in Settings → AI Models
(placeholders: {input} {output} {model} {index} {pitch} {f0}).
"""
from __future__ import annotations

from pathlib import Path

from . import tools
from .audio_io import read_audio, write_audio
from . import dsp

F0_METHODS = ("rmvpe", "harvest", "pm")


def convert(src: str | Path, dst: str | Path, model: str | Path, pitch: int = 0, f0: str = "rmvpe",
            index: str | Path | None = None, progress=None, cancel=None) -> dict:
    src, dst, model = Path(src), Path(dst), Path(model)
    if not model.exists():
        raise FileNotFoundError(f"RVC model not found: {model}")
    if f0 not in F0_METHODS:
        f0 = "rmvpe"
    dst.parent.mkdir(parents=True, exist_ok=True)
    argv = tools.build_argv("mlx_rvc", {"input": str(src), "output": str(dst.with_suffix(".wav")),
                                        "model": str(model), "pitch": int(pitch), "f0": f0,
                                        "index": str(index) if index else ""})
    if progress:
        progress(0.05, "RVC: converting the take")
    tools.run(argv, progress=progress, cancel=cancel, lo=0.05, hi=0.95, label="RVC", timeout=3600)
    out = dst.with_suffix(".wav")
    if not out.exists():
        raise RuntimeError("RVC wrote no file")
    # keep the take length identical: the session timeline relies on it
    a, sr = read_audio(src)
    b, sr2 = read_audio(out)
    if sr2 != sr:
        b = dsp.resample(b, sr2, sr)
    b = dsp.match_length(b, a.shape[1])
    write_audio(out, b, sr, 32, "wav")
    if progress:
        progress(1.0, "RVC done")
    return {"output": str(out), "model": str(model), "pitch": pitch, "f0": f0}
