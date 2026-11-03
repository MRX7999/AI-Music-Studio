"""External local AI tools: registry, discovery, command templates and a cancellable runner.

Every neural model lives outside the engine as an isolated command-line tool (one `uv tool`
environment per tool, or a Homebrew binary). The engine itself stays numpy/scipy only.
Reasons:
  * no dependency conflicts between MLX, PyTorch, transformers, numpy 1.x/2.x;
  * GPL tools (Matchering) are reached only through a process boundary;
  * the MLX build of a model can be swapped for the PyTorch build by changing one setting.

Each tool has a default argv template with {placeholders}. Users can override the
executable path and the template in Settings → AI Models, so a changed CLI flag in an
upstream release never requires an app update.
"""
from __future__ import annotations

import glob
import os
import platform
import queue
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

SEARCH_DIRS = [
    "~/.local/bin",                # uv tool install, pipx
    "/opt/homebrew/bin",           # Homebrew on Apple Silicon
    "/usr/local/bin",
    "~/.cargo/bin",
    "/usr/bin",
]

# Python environments where `pip install openai-whisper` & co. put their console scripts.
# Searched after SEARCH_DIRS; newest pyenv/conda versions first. pyenv shims are skipped on
# purpose: they only work for the version that is active in a shell.
ENV_BIN_GLOBS = [
    "~/.pyenv/versions/*/bin",
    "~/.pyenv/versions/*/envs/*/bin",
    "~/.virtualenvs/*/bin",
    "~/.venvs/*/bin",
    "~/.venv/bin",
    "~/venv/bin",
    "~/.ams-tools/*/bin",
    "~/miniforge3/bin", "~/miniforge3/envs/*/bin",
    "~/mambaforge/bin", "~/mambaforge/envs/*/bin",
    "~/miniconda3/bin", "~/miniconda3/envs/*/bin",
    "~/anaconda3/bin", "~/anaconda3/envs/*/bin",
    "/opt/homebrew/Caskroom/miniforge/base/bin", "/opt/homebrew/Caskroom/miniforge/base/envs/*/bin",
    "~/Library/Python/*/bin",
    "/Library/Frameworks/Python.framework/Versions/*/bin",
]


def _version_key(path: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", path)[:4]) or (0,)


def search_dirs() -> list[Path]:
    """Directories searched for tool executables, in order, without duplicates.

    The interpreter that runs the engine comes right after ~/.local/bin: when a user installs a tool
    with pip into the same Python (pyenv, venv, conda), the app finds it there."""
    out: list[Path] = []
    seen: set[str] = set()

    def add(d: str | Path):
        p = Path(os.path.expanduser(str(d)))
        key = str(p)
        if key not in seen and p.is_dir():
            seen.add(key)
            out.append(p)

    add(SEARCH_DIRS[0])
    add(Path(sys.executable).parent)
    for d in SEARCH_DIRS[1:]:
        add(d)
    for pattern in ENV_BIN_GLOBS:
        for d in sorted(glob.glob(os.path.expanduser(pattern)), key=_version_key, reverse=True):
            add(d)
    return out


def _runnable(p: Path) -> bool:
    """Executable file whose #! interpreter (if any) still exists — a moved venv leaves dead scripts."""
    if not (p.is_file() and os.access(p, os.X_OK)):
        return False
    try:
        with open(p, "rb") as fh:
            head = fh.read(256)
    except OSError:
        return False
    if head.startswith(b"#!"):
        line = head[2:].split(b"\n", 1)[0].decode("utf-8", "replace").strip()
        interp = line.split()[0] if line else ""
        if interp.startswith("/") and Path(interp).name != "env" and not Path(interp).exists():
            return False
    return True


@dataclass
class Tool:
    id: str
    label: str
    executables: list[str]
    template: str                   # argv template, shlex syntax
    feature: str                    # superres / lyrics / stems / cover / detect / voice / refmaster / video
    backend: str                    # mlx / torch / native / cloud
    install: str                    # pinned install command shown to the user
    license: str
    url: str
    version_args: list[str] = field(default_factory=lambda: ["--version"])
    apple_silicon_only: bool = False
    via_python: bool = False        # run {script} with the Python interpreter of the tool's own env


TOOLS: dict[str, Tool] = {t.id: t for t in [
    Tool("flashsr", "FlashSR (MLX, speech-swift)", ["speech"],
         "upsample {input} --variant {variant} --output {output}",
         "superres", "mlx", "brew install speech",
         "Apache-2.0 (speech-swift) / MIT (FlashSR weights)", "https://github.com/soniqo/speech-swift/blob/main/docs/models/flashsr.md",
         apple_silicon_only=True),
    Tool("audiosr", "AudioSR 0.0.7 (PyTorch)", ["audiosr"],
         "{script} {input} {output} --steps {steps} --guidance {guidance} --device {device}",
         "superres", "torch", "uv tool install audiosr==0.0.7",
         "MIT", "https://github.com/haoheliu/versatile_audio_super_resolution", via_python=True),
    Tool("mlx_whisper", "Whisper large-v3-turbo (MLX)", ["mlx_whisper"],
         "{input} --model {model} --word-timestamps True --output-format json --output-dir {outdir} "
         "--output-name {name} --condition-on-previous-text False",
         "lyrics", "mlx", "uv tool install mlx-whisper==0.4.3",
         "MIT", "https://pypi.org/project/mlx-whisper/", apple_silicon_only=True),
    Tool("whisper", "OpenAI Whisper (PyTorch)", ["whisper"],
         "{input} --model {model_torch} --word_timestamps True --output_format json --output_dir {outdir} "
         "--condition_on_previous_text False",
         "lyrics", "torch", "uv tool install openai-whisper==20250625",
         "MIT", "https://github.com/openai/whisper"),
    Tool("demucs_mlx", "Demucs htdemucs_6s (MLX)", ["demucs-mlx"],
         "-n {model} -o {outdir} {input}",
         "stems", "mlx", "uv tool install demucs-mlx==1.6.1",
         "MIT", "https://pypi.org/project/demucs-mlx/", version_args=["--help"], apple_silicon_only=True),
    Tool("demucs", "Demucs 4.0.1 (PyTorch)", ["demucs"],
         "-n {model} -o {outdir} {input}",
         "stems", "torch", "uv tool install demucs==4.0.1",
         "MIT", "https://github.com/facebookresearch/demucs", version_args=["--help"]),
    Tool("mflux", "Z-Image Turbo via mflux (MLX)", ["mflux-generate-z-image-turbo"],
         "--model {model} --prompt {prompt} --width {width} --height {height} --steps {steps} "
         "--seed {seed} --output {output}",
         "cover", "mlx", "uv tool install mflux==0.24.0",
         "MIT (mflux) / Apache-2.0 (Z-Image Turbo)", "https://github.com/filipstrand/mflux",
         version_args=["--help"], apple_silicon_only=True),
    Tool("aigm", "AI music detector ensemble (SpecTTTra on MLX)", ["aigm-detector"],
         "predict {input} --models {models} --backend {backend} --json",
         "detect", "mlx",
         "uv tool install \"aigm-detector[mlx] @ git+https://github.com/shoegazerstella/ai-music-detector"
         "@83db9aca8215db53dc539e217414e18ffdb633ad\"",
         "MIT (code); model weights have their own licenses", "https://github.com/shoegazerstella/ai-music-detector",
         version_args=["--help"]),
    Tool("mlx_rvc", "RVC voice conversion (MLX)", ["mlx-rvc"],
         "convert {input} {output} --model {model} --pitch {pitch} --f0-method {f0} --index {index}",
         "voice", "mlx",
         "uv tool install \"mlx-rvc @ git+https://github.com/lextoumbourou/mlx-rvc"
         "@f26633539f1aa935337d8ca5e96c78784698bd7a\"",
         "no license file in the repo (personal use)", "https://github.com/lextoumbourou/mlx-rvc",
         version_args=["--help"], apple_silicon_only=True),
    Tool("matchering", "Matchering 2.0.6 (reference mastering, GPLv3, separate process)", ["python3"],
         "{script} {input} {reference} {output}",
         "refmaster", "native",
         "uv venv ~/.ams-tools/matchering && uv pip install -p ~/.ams-tools/matchering matchering==2.0.6",
         "GPL-3.0 (not bundled)", "https://github.com/sergree/matchering", version_args=["--version"],
         via_python=True),
    Tool("ffmpeg", "FFmpeg (MP3/M4A/MP4 for publishing)", ["ffmpeg"],
         "", "video", "native", "brew install ffmpeg", "LGPL/GPL (system tool)", "https://ffmpeg.org",
         version_args=["-version"]),
]}

FEATURES = {
    "superres": ["flashsr", "audiosr"],
    "lyrics": ["mlx_whisper", "whisper"],
    "stems": ["demucs_mlx", "demucs"],
    "cover": ["mflux"],
    "detect": ["aigm"],
    "voice": ["mlx_rvc"],
    "refmaster": ["matchering"],
    "video": ["ffmpeg"],
}


class ToolConfig:
    """User overrides: {tool_id: {"path": "...", "template": "...", "enabled": bool}} and feature backends."""

    def __init__(self):
        self.overrides: dict[str, dict] = {}
        self.backends: dict[str, str] = {}      # feature -> tool id or "builtin" / "off"

    def update(self, data: dict | None):
        if not data:
            return
        for tid, o in (data.get("tools") or {}).items():
            if tid in TOOLS and isinstance(o, dict):
                self.overrides[tid] = {k: o[k] for k in ("path", "template", "enabled") if k in o}
        for feat, b in (data.get("backends") or {}).items():
            if feat in FEATURES and isinstance(b, str):
                self.backends[feat] = b

    def template(self, tid: str) -> str:
        t = (self.overrides.get(tid) or {}).get("template")
        return t if t else TOOLS[tid].template

    def enabled(self, tid: str) -> bool:
        return (self.overrides.get(tid) or {}).get("enabled", True) is not False


CONFIG = ToolConfig()


def is_apple_silicon() -> bool:
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def find_executable(tid: str, cfg: ToolConfig | None = None) -> str | None:
    cfg = cfg or CONFIG
    tool = TOOLS[tid]
    custom = ((cfg.overrides.get(tid) or {}).get("path") or "").strip()
    if custom:
        p = Path(os.path.expanduser(custom))
        return str(p) if p.is_file() and os.access(p, os.X_OK) else None
    if tid == "matchering":
        # a dedicated venv keeps GPL code out of the MIT engine process
        p = Path(os.path.expanduser("~/.ams-tools/matchering/bin/python"))
        return str(p) if p.is_file() else None
    dirs = search_dirs()
    for name in tool.executables:
        found = shutil.which(name)
        if found and _runnable(Path(found)) and "/.pyenv/shims/" not in found:
            return found
        for d in dirs:
            p = d / name
            if _runnable(p):
                return str(p)
    return None


def tool_python(exe: str) -> str:
    """Interpreter of the environment a console script belongs to (uv tool / pipx / venv)."""
    p = Path(exe)
    if p.name.startswith("python"):
        return str(p)
    try:
        with open(p, "rb") as fh:
            first = fh.readline(512).decode("utf-8", "replace").strip()
        if first.startswith("#!"):
            cand = first[2:].strip().split()[0]
            if Path(cand).name.startswith("python") and Path(cand).exists():
                return cand
    except OSError:
        pass
    for name in ("python", "python3"):
        c = p.resolve().parent / name
        if c.exists():
            return str(c)
    raise RuntimeError(f"Cannot find the Python interpreter of {exe}")


SCRIPTS_DIR = Path(__file__).resolve().parent / "ml_scripts"


def build_argv(tid: str, values: dict, cfg: ToolConfig | None = None, exe: str | None = None) -> list[str]:
    """Template → argv. Substitution happens per argument after shlex split, so values with
    spaces or quotes (paths, prompts) stay a single argument and no shell is ever involved."""
    cfg = cfg or CONFIG
    exe = exe or find_executable(tid, cfg)
    if not exe:
        raise ToolMissing(tid)
    if TOOLS[tid].via_python:
        exe = tool_python(exe)
        values = {"script": str(SCRIPTS_DIR / f"{tid}_run.py"), **values}
    argv = [exe]
    for part in shlex.split(cfg.template(tid)):
        names = re.findall(r"\{(\w+)\}", part)
        if not names:
            argv.append(part)
            continue
        if part == "{" + names[0] + "}" and len(names) == 1:
            v = values.get(names[0], "")
            if v is None or v == "":
                # an empty value removes the argument and the flag in front of it
                if len(argv) > 1 and argv[-1].startswith("-"):
                    argv.pop()
                continue
            argv.append(str(v))
            continue
        out = part
        for n in names:
            out = out.replace("{" + n + "}", str(values.get(n, "")))
        argv.append(out)
    return argv


class ToolMissing(RuntimeError):
    def __init__(self, tid: str):
        t = TOOLS[tid]
        super().__init__(f"{t.label} is not installed. Install: {t.install}")
        self.tool_id = tid


_PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s?%")


def run(argv: list[str], progress=None, cancel=None, timeout: float = 3600, cwd: str | None = None,
        lo: float = 0.0, hi: float = 1.0, label: str = "", env_extra: dict | None = None) -> str:
    """Runs a tool, streams percentages to `progress`, honours `cancel`. Returns combined output.

    The environment is reduced to what tools need: API keys of the studio are never inherited."""
    env = {k: v for k, v in os.environ.items()
           if not any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "PASSWORD"))}
    # the tool's own bin dir first: console scripts of a venv may call siblings (ffmpeg wrappers etc.)
    own = [str(Path(argv[0]).parent)] if os.path.isabs(argv[0]) else []
    env["PATH"] = os.pathsep.join(own + [os.path.expanduser(d) for d in SEARCH_DIRS] + [env.get("PATH", "")])
    env.update(env_extra or {})
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("TQDM_MININTERVAL", "1")
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd, env=env,
                            bufsize=0)
    q: "queue.Queue[bytes | None]" = queue.Queue()

    def _reader():
        buf = b""
        while True:
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            buf += chunk
            parts = re.split(rb"[\r\n]", buf)
            buf = parts.pop()
            for p in parts:
                q.put(p)
        if buf:
            q.put(buf)
        q.put(None)

    threading.Thread(target=_reader, daemon=True).start()
    lines: list[str] = []
    t0 = time.time()
    try:
        while True:
            try:
                raw = q.get(timeout=0.2)
            except queue.Empty:
                raw = b""
            if cancel and cancel():
                proc.terminate()
                raise RuntimeError("Cancelled")
            if time.time() - t0 > timeout:
                proc.kill()
                raise RuntimeError(f"{Path(argv[0]).name}: timeout after {timeout:.0f} s")
            if raw is None:
                break
            line = raw.decode("utf-8", "replace").rstrip()
            if not line.strip():
                continue
            if line.startswith("@progress "):
                # "@progress 41.2 Z-Image Turbo: 2.43 of 5.91 GB" from our own ml_scripts: exact text
                bits = line.split(None, 2)
                try:
                    pct = min(100.0, max(0.0, float(bits[1])))
                except (IndexError, ValueError):
                    pct = None
                if progress and pct is not None:
                    progress(lo + (hi - lo) * pct / 100.0, bits[2] if len(bits) > 2 else f"{label} {pct:.0f}%")
                continue
            lines.append(line)
            m = _PCT.findall(line)
            if progress and m:
                pct = min(100.0, float(m[-1]))
                progress(lo + (hi - lo) * pct / 100.0, f"{label} {pct:.0f}%".strip())
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    out = "\n".join(lines)
    if proc.returncode != 0:
        tail = "\n".join(lines[-15:])
        raise RuntimeError(f"{Path(argv[0]).name} exited with code {proc.returncode}:\n{tail}")
    return out


def probe_version(tid: str, exe: str) -> str:
    try:
        r = subprocess.run([exe] + TOOLS[tid].version_args, capture_output=True, text=True, timeout=20)
        text = (r.stdout or r.stderr or "").strip().splitlines()
        return text[0][:120] if text else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def doctor(cfg: ToolConfig | None = None, probe: bool = False) -> dict:
    """Status of every tool and the backend chosen per feature (MLX first on Apple Silicon)."""
    cfg = cfg or CONFIG
    apple = is_apple_silicon()
    tools = {}
    for tid, t in TOOLS.items():
        exe = find_executable(tid, cfg)
        tools[tid] = {
            "id": tid, "label": t.label, "feature": t.feature, "backend": t.backend,
            "installed": bool(exe), "path": exe or "", "install": t.install, "license": t.license,
            "url": t.url, "template": cfg.template(tid), "default_template": t.template,
            "enabled": cfg.enabled(tid), "supported": apple or not t.apple_silicon_only,
            "version": probe_version(tid, exe) if (probe and exe) else "",
        }
    # model files these tools need on top of the executable (checked offline, no network)
    if tools.get("mflux", {}).get("installed"):
        try:
            from . import cover as _cover
            tools["mflux"]["model"] = _cover.model_status()
        except Exception as e:  # noqa: BLE001 — a broken cache must not break the doctor
            tools["mflux"]["model"] = {"complete": False, "missing": [f"({e})"]}
    if tools.get("whisper", {}).get("installed"):
        from . import lyrics as _lyrics
        name, cached = _lyrics.torch_model()
        tools["whisper"]["model"] = {"name": name, "complete": cached}
    features = {}
    for feat, ids in FEATURES.items():
        want = cfg.backends.get(feat, "auto")
        got = resolve_backend(feat, cfg)
        features[feat] = {"backend": got, "candidates": ids, "wanted": want,
                          "fallback": want in TOOLS and got in TOOLS and got != want}
    return {"tools": tools, "features": features, "apple_silicon": apple,
            "search_dirs": [str(d) for d in search_dirs()]}


def resolve_backend(feature: str, cfg: ToolConfig | None = None) -> str:
    """Chosen tool id for a feature, "builtin" when only the internal fallback is usable, or "off"."""
    cfg = cfg or CONFIG
    want = cfg.backends.get(feature, "auto")
    if want == "off":
        return "off"
    if want not in ("auto", "builtin") and want in TOOLS:
        if cfg.enabled(want) and find_executable(want, cfg):
            return want
        # the chosen tool is not installed, but another one for the same job is
        # (e.g. mlx-whisper picked, openai-whisper installed): use it rather than fail
        for tid in FEATURES.get(feature, []):
            t = TOOLS[tid]
            if tid == want or (t.apple_silicon_only and not is_apple_silicon()):
                continue
            if cfg.enabled(tid) and find_executable(tid, cfg):
                return tid
        return "missing:" + want
    if want == "builtin":
        return "builtin"
    for tid in FEATURES.get(feature, []):
        t = TOOLS[tid]
        if t.apple_silicon_only and not is_apple_silicon():
            continue
        if cfg.enabled(tid) and find_executable(tid, cfg):
            return tid
    return "builtin"
