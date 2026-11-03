"""Media helpers for publishing: image sizes, MP3/M4A for Telegram, MP4 for YouTube."""
from __future__ import annotations

import shutil
import struct
import subprocess
from pathlib import Path

from .. import tools


def ffmpeg() -> str:
    exe = shutil.which("ffmpeg") or tools.find_executable("ffmpeg")
    if not exe:
        raise tools.ToolMissing("ffmpeg")
    return exe


def image_size(path: str | Path) -> tuple[int, int]:
    """(width, height) of a PNG or JPEG without image libraries."""
    data = Path(path).read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return int(w), int(h)
    if data[:2] == b"\xff\xd8":
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return int(w), int(h)
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg = struct.unpack(">H", data[i + 2:i + 4])[0]
            i += 2 + seg
    raise ValueError(f"Unsupported image: {path}")


def make_video(audio: str | Path, cover: str | Path, out: str | Path, style: str = "waveform",
               width: int = 1920, height: int = 1080, fps: int = 30, progress=None, cancel=None) -> Path:
    """Blurred cover background, sharp square cover, animated waveform or spectrum at the bottom."""
    audio, cover, out = Path(audio), Path(cover), Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    side = int(height * 0.72)
    bg = (f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
          f"boxblur=40:2,eq=brightness=-0.18[bgb];[0:v]scale={side}:{side}[fg];"
          f"[bgb][fg]overlay=(W-w)/2:{int(height * 0.06)}[bg]")
    wave_h = int(height * 0.16)
    if style == "spectrum":
        viz = (f"[1:a]showfreqs=s={width}x{wave_h}:mode=bar:ascale=log:fscale=log:colors=white,"
               f"format=rgba,colorchannelmixer=aa=0.8[w]")
    elif style == "still":
        viz = None
    else:
        viz = (f"[1:a]showwaves=s={width}x{wave_h}:mode=cline:rate={fps}:colors=white,"
               f"format=rgba,colorchannelmixer=aa=0.85[w]")
    if viz:
        graph = f"{bg};{viz};[bg][w]overlay=0:H-h-{int(height * 0.03)}:shortest=1,format=yuv420p[v]"
    else:
        graph = f"{bg};[bg]format=yuv420p[v]"
    vcodec = (["-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-r", "1"] if not viz else
              ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", str(fps)])
    cmd = [ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
           "-loop", "1", "-framerate", str(fps if viz else 1), "-i", str(cover), "-i", str(audio),
           "-filter_complex", graph, "-map", "[v]", "-map", "1:a", *vcodec,
           "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(out)]
    if progress:
        progress(0.05, "Rendering video (ffmpeg)")
    tools.run(cmd, cancel=cancel, timeout=3 * 3600)
    if not out.exists():
        raise RuntimeError("ffmpeg wrote no video")
    return out


def transcode(src: str | Path, dst: str | Path, fmt: str = "mp3", kbps: int = 320,
              metadata: dict | None = None, cover: str | Path | None = None) -> Path:
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(src)]
    if cover and Path(cover).exists():
        cmd += ["-i", str(cover), "-map", "0:a", "-map", "1:v", "-c:v", "mjpeg", "-disposition:v", "attached_pic"]
    if fmt == "mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", f"{kbps}k", "-id3v2_version", "3"]
    else:
        cmd += ["-c:a", "aac", "-b:a", f"{kbps}k"]
    for k, v in (metadata or {}).items():
        if v:
            cmd += ["-metadata", f"{k}={v}"]
    subprocess.run(cmd + [str(dst)], check=True)
    return dst
