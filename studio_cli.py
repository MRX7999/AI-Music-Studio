#!/usr/bin/env python3
"""AI Music Studio — командная строка (то же ядро, что и в интерфейсе).

Примеры:
  python studio_cli.py generate --engine demo --title "Тест" --duration 60
  python studio_cli.py generate --engine acestep --style "synthwave, male vocals" --lyrics-file song.txt
  python studio_cli.py session "song.flac" --method hpss --scene concert_hall -o out/session.studio.json
  python studio_cli.py render out/session.studio.json -o out/mix --format flac
  python studio_cli.py list scenes|mics|instruments
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from studio import __version__  # noqa: E402


def _progress(frac: float, msg: str = ""):
    bar = "#" * int(frac * 30)
    print(f"\r[{bar:<30}] {frac * 100:5.1f}%  {msg[:60]:<60}", end="", flush=True)
    if frac >= 1.0:
        print()


def cmd_generate(a):
    from studio.generators import GenerationRequest, get_engine
    lyrics = Path(a.lyrics_file).read_text(encoding="utf-8") if a.lyrics_file else (a.lyrics or "")
    req = GenerationRequest(title=a.title or "", style=a.style or "", lyrics=lyrics, instrumental=a.instrumental,
                            duration=a.duration, bpm=a.bpm, key=a.key or "", language=a.lang, seed=a.seed,
                            variations=a.variations, model=a.model or "",
                            extra=json.loads(a.extra) if a.extra else {})
    eng = get_engine(a.engine)
    ok, status = eng.is_available()
    print(f"{eng.name}: {status}")
    if not ok:
        return 2
    tracks = eng.generate(req, Path(a.out), progress=_progress)
    for t in tracks:
        print(f"  {t.path}" + (f"  (дорожки: {', '.join(t.stems)})" if t.stems else ""))
    return 0


def cmd_session(a):
    from studio import stems as stems_mod
    from studio.session import session_from_stems
    src = Path(a.song)
    out = Path(a.output) if a.output else src.parent / f"{src.stem} — studio" / "session.studio.json"
    if out.suffix.lower() != ".json":        # -o указывает на папку сессии
        out = out / "session.studio.json"
    sidecar = src.with_suffix(".json")
    meta, stems = {"title": src.stem, "source": str(src)}, None
    if sidecar.exists():
        from studio.generators.base import GeneratedTrack
        t = GeneratedTrack.from_sidecar(sidecar)
        meta.update(t.meta)
        meta["title"] = t.title or meta["title"]
        stems = {k: v for k, v in t.stems.items() if v and Path(v).exists()} or None
    if not stems:
        stems = stems_mod.separate(src, out.parent / "stems", a.method, progress=_progress)
    s = session_from_stems({k: str(v) for k, v in stems.items()}, name=meta["title"], scene=a.scene, meta=meta)
    s.save(out)
    print(f"Сессия: {out}  · каналов: {len(s.channels)}")
    return 0


def cmd_render(a):
    from studio.render import render_session
    from studio.session import Session
    s = Session.load(a.session)
    if a.scene:
        s.set_scene(a.scene)
    if a.format:
        s.recording.output_format = a.format
    if a.lufs is not None:
        s.recording.target_lufs = a.lufs
    out = Path(a.output) if a.output else Path(a.session).parent / "renders" / f"{s.name} — {s.scene}"
    r = render_session(s, start_s=a.start, duration_s=a.duration, out_path=out,
                       export_stems_dir=(out.parent / f"{out.name} — stems") if a.stems else None,
                       progress=_progress)
    print(f"Файл: {r.path}")
    print(json.dumps(r.report["master"], ensure_ascii=False))
    return 0


def cmd_list(a):
    if a.what == "scenes":
        from studio.scenes import SCENES
        for k, s in SCENES.items():
            print(f"{k:14} {s.name:42} {s.width:g}×{s.depth:g}×{s.height:g} м  RT60 {s.rt60} с")
    elif a.what == "mics":
        from studio.mics import MICS
        for k, m in MICS.items():
            print(f"{k:14} {m.name:48} {m.pattern}")
    else:
        from studio.session import INSTRUMENTS
        for k, p in INSTRUMENTS.items():
            print(f"{k:10} {p.name:26} микрофон {p.mic}, {p.distance_cm:g} см")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="studio_cli", description=f"AI Music Studio {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="сгенерировать песню")
    g.add_argument("--engine", default="acestep", choices=["acestep", "gptunnel", "demo"])
    g.add_argument("--title")
    g.add_argument("--style", help="жанр/настроение/инструменты")
    g.add_argument("--lyrics")
    g.add_argument("--lyrics-file")
    g.add_argument("--instrumental", action="store_true")
    g.add_argument("--duration", type=float, default=120)
    g.add_argument("--bpm", type=int)
    g.add_argument("--key")
    g.add_argument("--lang", default="ru")
    g.add_argument("--seed", type=int)
    g.add_argument("--variations", type=int, default=1)
    g.add_argument("--model")
    g.add_argument("--extra", help='JSON с параметрами движка, например {"inference_steps": 8}')
    g.add_argument("--out", default=str(Path.home() / "Music" / "AI Music Studio" / "generated"))
    g.set_defaults(fn=cmd_generate)

    s = sub.add_parser("session", help="создать сессию студии из песни")
    s.add_argument("song")
    s.add_argument("--method", default="hpss", choices=["hpss", "demucs", "none"])
    s.add_argument("--scene", default="studio_a")
    s.add_argument("-o", "--output")
    s.set_defaults(fn=cmd_session)

    r = sub.add_parser("render", help="записать микс сессии")
    r.add_argument("session")
    r.add_argument("-o", "--output")
    r.add_argument("--scene")
    r.add_argument("--format", choices=["wav", "flac", "alac", "mp3"])
    r.add_argument("--lufs", type=float)
    r.add_argument("--start", type=float, default=0.0)
    r.add_argument("--duration", type=float)
    r.add_argument("--stems", action="store_true", help="сохранить дорожки каналов")
    r.set_defaults(fn=cmd_render)

    li = sub.add_parser("list", help="список помещений / микрофонов / инструментов")
    li.add_argument("what", choices=["scenes", "mics", "instruments"])
    li.set_defaults(fn=cmd_list)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
