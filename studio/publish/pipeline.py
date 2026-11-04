"""Release steps (super-resolution → reference master → cover → lyrics → AI check → package) and upload jobs."""
from __future__ import annotations

import time
from pathlib import Path

from .. import cover as cover_mod
from .. import detect, humanize as humanize_mod, lyrics, refmaster, superres
from ..audio_io import read_audio
from . import media, package, telegram, youtube
from .release import PublishQueue, Release

STEPS = ("superres", "refmaster", "cover", "lyrics", "humanize", "detect", "package")


def run_step(root: Path, rel: Release, step: str, opts: dict, keys: dict, progress=None, cancel=None) -> Release:
    folder = rel.folder(root)
    if step == "superres":
        rep = superres.upscale(rel.source, folder / "master.wav", export_sr=int(opts.get("export_sr", 48000)),
                               backend=opts.get("backend") or None, mode=opts.get("mode", "mid"),
                               force=bool(opts.get("force")), high_gain_db=float(opts.get("high_gain_db", 0.0)),
                               steps=int(opts.get("steps", 12)), guidance=float(opts.get("guidance", 2.0)),
                               two_pass=bool(opts.get("two_pass", True)), progress=progress, cancel=cancel)
        rel.superres = rep
        rel.master = rep["output"]
        if not rep.get("skipped"):
            tools_used = rel.meta.setdefault("ai", {}).setdefault("tools", [])
            tag = f"super-resolution: {rep['backend']}"
            if tag not in tools_used:
                tools_used.append(tag)
    elif step == "refmaster":
        ref = (opts.get("reference") or "").strip()
        if not ref:
            rel.meta["refmaster"] = {"skipped": "no reference track chosen"}
        else:
            src = rel.master or rel.source
            if Path(src).name == "master_ref.wav":          # re-run: start again from the pre-match master
                src = rel.meta.get("refmaster", {}).get("input") or rel.source
            rep = refmaster.master(src, Path(ref).expanduser(), folder / "master_ref.wav",
                                   bits=int(opts.get("bits", 24)), use_limiter=bool(opts.get("use_limiter", True)),
                                   backend=opts.get("backend") or None, strength=float(opts.get("strength", 1.0)),
                                   max_db=float(opts.get("max_db", 6.0)), progress=progress, cancel=cancel)
            rep["input"], rep["reference"] = str(src), str(Path(ref).expanduser())
            rel.meta["refmaster"] = rep
            rel.master = rep["output"]
    elif step == "cover":
        prompt = opts.get("prompt") or cover_mod.build_prompt(rel.title, rel.meta.get("genre", ""),
                                                             rel.meta.get("mood", ""), opts.get("extra", ""))
        if opts.get("file"):
            src = Path(opts["file"]).expanduser()
            c = cover_mod.image_convert(src, folder / "cover.jpg", cover_mod.SIZE, "jpeg")
            t = cover_mod.image_convert(c, folder / "cover_thumb.jpg", 320, "jpeg", 80)
            res = {"cover": str(c), "thumb": str(t), "backend": "file", "prompt": ""}
        else:
            seed = opts.get("seed")
            res = cover_mod.generate(folder / "cover", prompt, seed=int(seed) if seed not in (None, "") else None,
                                     backend=opts.get("backend") or None, audio_path=rel.master,
                                     progress=progress, cancel=cancel)
        rel.cover, rel.thumb = res["cover"], res.get("thumb", "")
        rel.meta["cover_info"] = {k: res.get(k) for k in ("backend", "prompt", "seed")}
    elif step == "lyrics":
        if opts.get("lrc_text"):
            lines = lyrics.parse_lrc(opts["lrc_text"])
            (folder / "lyrics.lrc").write_text(opts["lrc_text"], encoding="utf-8")
            (folder / "lyrics.srt").write_text(lyrics.to_srt(lines), encoding="utf-8")
            rel.lrc, rel.srt = str(folder / "lyrics.lrc"), str(folder / "lyrics.srt")
        else:
            a, sr = read_audio(rel.master)
            res = lyrics.build(opts.get("vocals") or rel.master, rel.lyrics_text, folder, rel.title, rel.artist,
                               language=opts.get("language", ""), duration=a.shape[1] / sr,
                               progress=progress, cancel=cancel)
            p = Path(res["lrc"])
            p.replace(folder / "lyrics.lrc")
            Path(res["srt"]).replace(folder / "lyrics.srt")
            rel.lrc, rel.srt = str(folder / "lyrics.lrc"), str(folder / "lyrics.srt")
            rel.meta["lyrics_info"] = {k: res[k] for k in ("backend", "language", "matched", "total")}
    elif step == "humanize":
        # the user's own humanization pass (studio/humanize.py, was humanize.py since 1.0.0):
        # 12 production steps (pitch micro-warp, timing jitter, tape saturation, air, noise,
        # stereo drift, EQ randomize, phase dither, subsample scatter, room reverb). Runs once
        # before the AI check; audio is never changed based on the detector verdict.
        preset = opts.get("preset", "ultra-low")
        if preset not in humanize_mod.PRESETS:
            preset = "ultra-low"
        seed = opts.get("seed")
        seed = int(seed) if str(seed).lstrip("-").isdigit() else 42
        src = rel.master or rel.source
        if opts.get("restore"):          # undo: package and detect go back to the pre-humanize master
            prev = rel.meta.get("humanize", {}).get("input")
            rel.master = prev or src
            rel.meta["humanize"] = {"restored": True, "input": str(src)}
        else:
            out = folder / "master_humanized.wav"
            humanize_mod.humanize(Path(src), out, preset=preset, seed=seed,
                                  skip_noise=bool(opts.get("skip_noise")), skip_stretch=True,
                                  verbose=False)
            rel.meta["humanize"] = {"preset": preset, "seed": seed, "input": str(src),
                                    "output": str(out), "skipped_noise": bool(opts.get("skip_noise"))}
            rel.master = str(out)
            tools_used = rel.meta.setdefault("ai", {}).setdefault("tools", [])
            tag = f"humanization: {preset}"
            if tag not in tools_used:
                tools_used.append(tag)
    elif step == "detect":
        rep = detect.check(rel.master, detectors=opts.get("detectors") or None, keys=keys,
                           threshold=float(opts.get("threshold", 0.5)), progress=progress, cancel=cancel)
        detect.save_report(rep, folder)
        rel.ai_report = rep
    elif step == "package":
        # format options like in Export; the publish queue reuses the last ones chosen for this release
        po = package.options(opts if any(k in opts for k in package.options({})) else
                             rel.meta.get("package_options") or {})
        rel.meta["package_options"] = po
        res = package.build(rel.master, folder / "package",
                            {**rel.meta, "title": rel.title, "artist": rel.artist},
                            cover=rel.cover or None, lyrics_text=rel.lyrics_text, lrc_path=rel.lrc or None,
                            ai_report=rel.ai_report or None, progress=progress, opts=po)
        rel.meta["package"] = res
    else:
        raise ValueError(f"unknown step {step}")
    rel.save(root)
    return rel


def _ai_note(rel: Release, lang: str) -> str:
    if not (rel.meta.get("ai") or {}).get("generated", True):
        return ""
    return "Создано с помощью ИИ" if lang == "ru" else "Made with AI"


def youtube_description(rel: Release, lang: str = "en") -> str:
    parts = []
    if rel.meta.get("description"):
        parts.append(rel.meta["description"].strip())
    if rel.lyrics_text.strip():
        clean = "\n".join(ln["text"] for ln in lyrics.parse_lyrics(rel.lyrics_text))
        parts.append(("Текст:\n" if lang == "ru" else "Lyrics:\n") + clean)
    note = _ai_note(rel, lang)
    if note:
        tools_used = ", ".join((rel.meta.get("ai") or {}).get("tools") or [])
        parts.append(note + (f" ({tools_used})" if tools_used else ""))
    return "\n\n".join(parts)


def run_job(root: Path, queue: PublishQueue, job: dict, keys: dict, progress=None, cancel=None) -> dict:
    """Executes one queue job. Transient errors put it back into the queue with back-off."""
    rel = Release.load(root, job["release"])
    opts = job.get("options") or {}
    folder = rel.folder(root)
    queue.update(job["id"], status="running")
    try:
        if job["service"] == "telegram":
            token, chat = keys.get("TELEGRAM_BOT_TOKEN"), opts.get("chat_id") or keys.get("TELEGRAM_CHAT_ID")
            if not token or not chat:
                raise telegram.TelegramError("Telegram bot token or chat id is not set", permanent=True)
            mp3 = folder / "telegram.mp3"
            if not mp3.exists() or mp3.stat().st_mtime < Path(rel.master).stat().st_mtime:
                if progress:
                    progress(0.1, "Telegram: MP3 320 kbps")
                media.transcode(rel.master, mp3, "mp3", 320, {"title": rel.title, "artist": rel.artist},
                                rel.cover or None)
            a, sr = read_audio(mp3)
            cap = telegram.build_caption(rel.title, rel.artist, opts.get("caption", ""),
                                         _ai_note(rel, opts.get("lang", "en")) if opts.get("ai_note", True) else "",
                                         rel.meta.get("tags") or [])
            if progress:
                progress(0.4, "Telegram: uploading")
            res = telegram.send_audio(token, str(chat), mp3, rel.title, rel.artist, int(a.shape[1] / sr), cap,
                                      rel.thumb or None, silent=bool(opts.get("silent")), confirmed=True)
        elif job["service"] == "youtube":
            cid, cs, rt = keys.get("YOUTUBE_CLIENT_ID"), keys.get("YOUTUBE_CLIENT_SECRET"), keys.get("YOUTUBE_REFRESH_TOKEN")
            if not (cid and cs and rt):
                raise youtube.YouTubeError("YouTube is not connected", permanent=True)
            if not rel.cover:
                raise youtube.YouTubeError("A cover is required for the video", permanent=True)
            mp4 = folder / "youtube.mp4"
            if not mp4.exists() or mp4.stat().st_mtime < max(Path(rel.master).stat().st_mtime,
                                                             Path(rel.cover).stat().st_mtime):
                media.make_video(rel.master, rel.cover, mp4, style=opts.get("video_style", "waveform"),
                                 progress=progress, cancel=cancel)
            body = youtube.build_body(opts.get("title") or (f"{rel.artist} — {rel.title}" if rel.artist else rel.title),
                                      opts.get("description") or youtube_description(rel, opts.get("lang", "en")),
                                      rel.meta.get("tags") or [], opts.get("privacy", "private"),
                                      opts.get("publish_at", ""),
                                      synthetic=bool((rel.meta.get("ai") or {}).get("generated", True)),
                                      language=rel.meta.get("language", ""))
            res = youtube.upload(mp4, body, cid, cs, rt, progress=progress, cancel=cancel, confirmed=True,
                                 confirm_public=bool(opts.get("confirm_public")))
        elif job["service"] == "package":
            po = {k: v for k, v in opts.items() if k in package.options({})}
            rel = run_step(root, rel, "package", po, keys, progress, cancel)
            res = {"service": "package", "url": "", "folder": rel.meta["package"]["folder"],
                   "ok": rel.meta["package"]["ok"]}
        else:
            raise ValueError(f"unknown service {job['service']}")
        return queue.done(job, res)
    except PermissionError as e:
        return queue.fail(job, str(e), permanent=True)
    except (telegram.TelegramError, youtube.YouTubeError) as e:
        quota = "limit" in str(e).lower()
        return queue.fail(job, str(e), permanent=getattr(e, "permanent", False), quota=quota)
    except Exception as e:  # noqa: BLE001
        if "Cancelled" in str(e):
            return queue.update(job["id"], status="pending", error="cancelled")
        return queue.fail(job, f"{type(e).__name__}: {e}", permanent=False)


def summary(rel: Release) -> dict:
    d = rel.to_dict()
    d["ready"] = {
        "superres": bool(rel.superres), "refmaster": Path(rel.master or "").name == "master_ref.wav",
        "cover": bool(rel.cover), "lyrics": bool(rel.lrc),
        "detect": bool(rel.ai_report), "package": bool(rel.meta.get("package")),
    }
    d["age_s"] = round(time.time() - rel.created, 1)
    return d
