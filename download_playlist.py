#!/usr/bin/env python3
"""
Скачивает треки из плейлиста gptunnel/Suno и готовит их к импорту в Apple Music.

Источники отдаются в MP3 (родной формат, без потерь от перекодирования).
По умолчанию скрипт сохраняет оригинальные MP3 с тегами и обложкой.
С флагом --flac или --alac дополнительно перекодирует в FLAC или ALAC
(Apple Lossless, .m4a). Это lossless-обёртка; качество не выше исходного MP3 —
настоящего lossless на сервере нет. ALAC импортируется в Apple Music нативно.

Зависимости:
    pip install requests mutagen pillow
    ffmpeg в PATH (для --flac / --alac / --master / --lyrics)
    pillow необязателен — конвертирует WebP-обложки в JPEG для Apple Music

    Опционально, улучшение качества:
      --upscale (AI):  pip install audiosr           # локально, MPS на Apple Silicon
      --master  (ffmpeg): встроено, доп. зависимостей нет

    Опционально, lyrics (whisper.cpp, локально):
      brew install whisper-cpp
      # модель large-v3 (~3 ГБ): из репо whisper.cpp
      #   bash ./models/download-ggml-model.sh large-v3
      # и укажи путь: --whisper-model models/ggml-large-v3.bin

Примеры:
    python3 download_playlist.py --alac
    python3 download_playlist.py --alac --master
    python3 download_playlist.py --alac --upscale --master
    python3 download_playlist.py --alac --lyrics --whisper-model models/ggml-large-v3.bin
    python3 download_playlist.py --url "https://app.gptunnel.ai/app/ipod?playlist=XXXX" --out ~/Music/Suno
"""

import argparse
import os
import re
import subprocess
import sys
import shutil
from urllib.parse import urlparse, parse_qs

try:
    import requests
except ImportError:
    sys.exit("Нужен пакет requests:  pip install requests")

try:
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC, USLT, error as id3error
    from mutagen.mp3 import MP3
    from mutagen.flac import FLAC, Picture
    from mutagen.mp4 import MP4, MP4Cover
    HAVE_MUTAGEN = True
except ImportError:
    HAVE_MUTAGEN = False

try:
    from PIL import Image
    import io
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

API_BASE = "https://app.gptunnel.ai/x/suno_playlist_"
# Ссылка на плейлист: --url или переменная окружения GPTUNNEL_PLAYLIST_URL (см. .env.example)
DEFAULT_URL = os.environ.get("GPTUNNEL_PLAYLIST_URL", "")
# Название альбома в тегах: --album или GPTUNNEL_ALBUM_NAME
ALBUM_NAME = os.environ.get("GPTUNNEL_ALBUM_NAME", "Suno Playlist")


def playlist_id_from_url(url: str) -> str:
    q = parse_qs(urlparse(url).query)
    if "playlist" in q:
        return q["playlist"][0]
    # допускаем, что передан просто id
    m = re.search(r"([0-9a-f]{16,})", url)
    if m:
        return m.group(1)
    raise ValueError(f"Не удалось извлечь id плейлиста из: {url}")


def safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip()
    return name or "track"


def fetch_playlist(pid: str) -> list:
    url = API_BASE + pid
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://app.gptunnel.ai/",
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    # API возвращает объект с числовыми ключами "0","1",... либо список
    if isinstance(data, dict):
        tracks = [data[k] for k in sorted(data.keys(), key=lambda x: int(x))]
    else:
        tracks = data
    return tracks


def download(url: str, dest: str):
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://app.gptunnel.ai/"}
    with requests.get(url, headers=headers, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)


def get_cover(url: str) -> bytes | None:
    if not url:
        return None
    try:
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://app.gptunnel.ai/"}
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.content
        # Apple Music надёжнее показывает JPEG, чем WebP — конвертируем при возможности
        if HAVE_PIL:
            try:
                img = Image.open(io.BytesIO(data)).convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=90)
                return buf.getvalue()
            except Exception:
                pass
        return data
    except Exception as e:
        print(f"   ! обложка не скачана: {e}")
        return None


def tag_mp3(path: str, title: str, artist: str, cover: bytes | None, cover_mime: str,
            lyrics: str | None = None):
    if not HAVE_MUTAGEN:
        return
    try:
        audio = MP3(path, ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        tags.add(TIT2(encoding=3, text=title))
        tags.add(TPE1(encoding=3, text=artist))
        tags.add(TALB(encoding=3, text=ALBUM_NAME))
        if cover:
            tags.add(APIC(encoding=3, mime=cover_mime, type=3, desc="Cover", data=cover))
        if lyrics:
            tags.add(USLT(encoding=3, lang="eng", desc="", text=lyrics))
        audio.save()
    except id3error as e:
        print(f"   ! не удалось записать ID3: {e}")


def tag_flac(path: str, title: str, artist: str, cover: bytes | None, cover_mime: str,
             lyrics: str | None = None):
    if not HAVE_MUTAGEN:
        return
    audio = FLAC(path)
    audio["title"] = title
    audio["artist"] = artist
    audio["album"] = ALBUM_NAME
    if lyrics:
        audio["lyrics"] = lyrics
        audio["unsyncedlyrics"] = lyrics
    if cover:
        pic = Picture()
        pic.type = 3
        pic.mime = cover_mime
        pic.desc = "Cover"
        pic.data = cover
        audio.add_picture(pic)
    audio.save()


def to_flac(src_mp3: str, dst_flac: str):
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg не найден в PATH — он нужен для --flac")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", src_mp3,
         "-map", "0:a", "-vn", "-c:a", "flac", "-compression_level", "8", dst_flac],
        check=True,
    )


def to_alac(src_mp3: str, dst_m4a: str):
    """Перекодирует MP3 в ALAC (Apple Lossless) в контейнере .m4a."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg не найден в PATH — он нужен для --alac")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", src_mp3,
         "-map", "0:a", "-vn", "-c:a", "alac", dst_m4a],
        check=True,
    )


def tag_alac(path: str, title: str, artist: str, cover: bytes | None, cover_mime: str,
             lyrics: str | None = None):
    if not HAVE_MUTAGEN:
        return
    audio = MP4(path)
    audio["\xa9nam"] = [title]
    audio["\xa9ART"] = [artist]
    audio["\xa9alb"] = [ALBUM_NAME]
    if lyrics:
        audio["\xa9lyr"] = [lyrics]
    if cover:
        fmt = MP4Cover.FORMAT_PNG if cover_mime == "image/png" else MP4Cover.FORMAT_JPEG
        audio["covr"] = [MP4Cover(cover, imageformat=fmt)]
    audio.save()


# --------------------------------------------------------------------------
# Улучшение качества
# --------------------------------------------------------------------------
#
# ВАЖНО: исходник — MP3 с потерями. Выброшенную кодеком информацию
# математически вернуть нельзя. --master выравнивает громкость/убирает
# клиппинг; --upscale нейросетью достраивает правдоподобные высокие
# частоты (это реконструкция, а не восстановление оригинала).

def master_audio(src_mp3, dst_wav):
    """Тех-мастеринг через ffmpeg: loudness EBU R128 (-14 LUFS) + мягкий лимитер."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg не найден в PATH — он нужен для --master")
    af = "loudnorm=I=-14:TP=-1.5:LRA=11,alimiter=limit=0.97"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", src_mp3,
         "-map", "0:a", "-vn", "-af", af,
         "-ar", "44100", "-c:a", "pcm_s16le", dst_wav],
        check=True,
    )
    return dst_wav


def _all_wavs(root):
    out = []
    for dirpath, _, files in os.walk(root):
        for f in files:
            if f.lower().endswith(".wav"):
                out.append(os.path.join(dirpath, f))
    return out


def upscale_audio(src_path, dst_wav, ddim_steps=50):
    """AI-апскейлинг через AudioSR (локально, MPS на Apple Silicon).
    Достраивает спектр до 48 кГц. Требует: pip install audiosr
    При первом запуске скачает модель (несколько ГБ)."""
    if not shutil.which("audiosr"):
        raise RuntimeError(
            "утилита audiosr не найдена. Установи:  pip install audiosr\n"
            "   (на Apple Silicon работает через MPS; первый запуск скачивает модель)")
    outdir = os.path.dirname(dst_wav) or "."
    before = set(_all_wavs(outdir))
    subprocess.run(
        ["audiosr", "-i", src_path, "-s", outdir,
         "--ddim_steps", str(ddim_steps), "--device", "auto"],
        check=True,
    )
    after = set(_all_wavs(outdir))
    new = sorted(after - before, key=lambda p: os.path.getmtime(p), reverse=True)
    if not new:
        raise RuntimeError("audiosr не создал выходной файл")
    shutil.move(new[0], dst_wav)
    return dst_wav


# --------------------------------------------------------------------------
# Lyrics через whisper.cpp
# --------------------------------------------------------------------------

def _format_lrc_time(seconds):
    m = int(seconds // 60)
    s = seconds - m * 60
    return "[{:02d}:{:05.2f}]".format(m, s)


def transcribe_whisper(src_audio, model_path, whisper_bin, lang="auto"):
    """Распознаёт вокал через whisper.cpp и возвращает (plain_text, lrc_text)."""
    if not (shutil.which(whisper_bin) or os.path.exists(whisper_bin)):
        raise RuntimeError(
            "бинарник whisper.cpp '{}' не найден.\n".format(whisper_bin) +
            "   Установка:  brew install whisper-cpp   "
            "(или собери из github.com/ggerganov/whisper.cpp)")
    if not os.path.exists(model_path):
        raise RuntimeError(
            "модель '{}' не найдена.\n".format(model_path) +
            "   Скачай:  bash ./models/download-ggml-model.sh large-v3")

    tmp_wav = src_audio + ".whisper16k.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", src_audio,
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", tmp_wav],
        check=True,
    )
    out_prefix = src_audio + ".whisper"
    cmd = [whisper_bin, "-m", model_path, "-f", tmp_wav, "-osrt", "-of", out_prefix]
    if lang and lang != "auto":
        cmd += ["-l", lang]
    subprocess.run(cmd, check=True)
    srt_path = out_prefix + ".srt"

    plain_lines, lrc_lines = [], []
    if os.path.exists(srt_path):
        with open(srt_path, encoding="utf-8") as fh:
            block_text, block_start = [], None
            for raw in fh:
                line = raw.strip()
                if "-->" in line:
                    start = line.split("-->")[0].strip().replace(",", ".")
                    h, m, rest = start.split(":")
                    block_start = int(h) * 3600 + int(m) * 60 + float(rest)
                elif line and not line.isdigit():
                    block_text.append(line)
                elif not line and block_text:
                    txt = " ".join(block_text)
                    plain_lines.append(txt)
                    if block_start is not None:
                        lrc_lines.append(_format_lrc_time(block_start) + txt)
                    block_text, block_start = [], None
            if block_text:
                txt = " ".join(block_text)
                plain_lines.append(txt)
                if block_start is not None:
                    lrc_lines.append(_format_lrc_time(block_start) + txt)

    for p in (tmp_wav, srt_path):
        try:
            os.remove(p)
        except OSError:
            pass

    return "\n".join(plain_lines), "\n".join(lrc_lines)


def _cleanup(paths):
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except OSError:
            pass


def main():
    global ALBUM_NAME
    ap = argparse.ArgumentParser(description="Скачать плейлист Suno/gptunnel для Apple Music")
    ap.add_argument("--url", default=DEFAULT_URL,
                    help="ссылка на плейлист или его id (по умолч. из GPTUNNEL_PLAYLIST_URL)")
    ap.add_argument("--album", default=None, help=f"название альбома в тегах (по умолч. «{ALBUM_NAME}»)")
    ap.add_argument("--out", default="suno_music", help="папка для сохранения")
    fmt = ap.add_mutually_exclusive_group()
    fmt.add_argument("--flac", action="store_true", help="перекодировать в FLAC (обёртка, не повышает качество)")
    fmt.add_argument("--alac", action="store_true", help="перекодировать в ALAC / Apple Lossless .m4a (нативно для Apple Music)")
    ap.add_argument("--keep-mp3", action="store_true", help="при --flac/--alac сохранить и оригинальный MP3")

    ap.add_argument("--master", action="store_true",
                    help="тех-мастеринг ffmpeg: loudness EBU R128 + лимитер (выравнивает звук)")
    ap.add_argument("--upscale", action="store_true",
                    help="AI-апскейлинг через AudioSR (локально, MPS; pip install audiosr)")
    ap.add_argument("--ddim-steps", type=int, default=50,
                    help="шаги диффузии AudioSR (больше = чище/медленнее, по умолч. 50)")

    ap.add_argument("--lyrics", action="store_true",
                    help="распознать текст песен локальным whisper.cpp (.lrc + встройка в теги)")
    ap.add_argument("--whisper-bin", default="whisper-cli",
                    help="бинарник whisper.cpp (по умолч. whisper-cli; бывает 'whisper' / 'main')")
    ap.add_argument("--whisper-model", default="models/ggml-large-v3.bin",
                    help="путь к ggml-модели (по умолч. models/ggml-large-v3.bin)")
    ap.add_argument("--whisper-lang", default="auto",
                    help="язык вокала для Whisper (auto / en / ru / ...)")
    args = ap.parse_args()
    if not args.url:
        ap.error("укажите --url или переменную окружения GPTUNNEL_PLAYLIST_URL")
    if args.album:
        ALBUM_NAME = args.album

    pid = playlist_id_from_url(args.url)
    out = os.path.expanduser(args.out)
    os.makedirs(out, exist_ok=True)

    print(f"Плейлист: {pid}")
    if not HAVE_MUTAGEN:
        print("! Пакет mutagen не установлен — теги/обложки записаны не будут (pip install mutagen)")

    tracks = fetch_playlist(pid)
    print(f"Найдено треков: {len(tracks)}\n")

    ok = 0
    for i, t in enumerate(tracks, 1):
        title = (t.get("title") or f"track_{i}").strip()
        artist = (t.get("artist") or "Suno").strip()
        audio_url = t.get("audio_url")
        image_url = t.get("image_url")
        if not audio_url:
            print(f"[{i}/{len(tracks)}] {title} — нет audio_url, пропуск")
            continue

        base = f"{i:02d} - {safe_name(title)}"
        mp3_path = os.path.join(out, base + ".mp3")
        print(f"[{i}/{len(tracks)}] {title} — {artist}")

        try:
            download(audio_url, mp3_path)
        except Exception as e:
            print(f"   ! ошибка загрузки: {e}")
            continue

        cover = get_cover(image_url)
        # после get_cover обложка приведена к JPEG (если установлен Pillow)
        cover_mime = "image/jpeg" if HAVE_PIL else (
            "image/webp" if (image_url or "").endswith(".webp") else "image/jpeg")

        temps = []
        cur = mp3_path  # исходник для кодирования; меняется после master/upscale

        try:
            if args.master:
                mastered = os.path.join(out, base + ".mastered.wav")
                print("   · мастеринг (loudnorm)…")
                master_audio(cur, mastered)
                cur = mastered
                temps.append(mastered)
            if args.upscale:
                upscaled = os.path.join(out, base + ".upscaled.wav")
                print("   · AI-апскейлинг (AudioSR)… может быть долго")
                upscale_audio(cur, upscaled, ddim_steps=args.ddim_steps)
                cur = upscaled
                temps.append(upscaled)
        except Exception as e:
            print(f"   ! улучшение качества пропущено: {e}")
            cur = mp3_path

        plain_lyrics, lrc_lyrics = None, None
        if args.lyrics:
            try:
                print("   · распознавание текста (whisper.cpp)…")
                plain_lyrics, lrc_lyrics = transcribe_whisper(
                    cur, args.whisper_model, args.whisper_bin, args.whisper_lang)
                if lrc_lyrics:
                    with open(os.path.join(out, base + ".lrc"), "w", encoding="utf-8") as fh:
                        fh.write(f"[ti:{title}]\n[ar:{artist}]\n[al:{ALBUM_NAME}]\n" + lrc_lyrics + "\n")
                    print(f"   ✓ {base}.lrc")
            except Exception as e:
                print(f"   ! lyrics пропущены: {e}")

        if args.flac:
            flac_path = os.path.join(out, base + ".flac")
            try:
                to_flac(cur, flac_path)
                tag_flac(flac_path, title, artist, cover, cover_mime, lyrics=plain_lyrics)
                if not args.keep_mp3:
                    os.remove(mp3_path)
                print(f"   ✓ {os.path.basename(flac_path)}")
            except Exception as e:
                print(f"   ! ошибка FLAC: {e}")
                _cleanup(temps)
                continue
        elif args.alac:
            m4a_path = os.path.join(out, base + ".m4a")
            try:
                to_alac(cur, m4a_path)
                tag_alac(m4a_path, title, artist, cover, cover_mime, lyrics=plain_lyrics)
                if not args.keep_mp3:
                    os.remove(mp3_path)
                print(f"   ✓ {os.path.basename(m4a_path)}")
            except Exception as e:
                print(f"   ! ошибка ALAC: {e}")
                _cleanup(temps)
                continue
        else:
            if cur != mp3_path:
                final_wav = os.path.join(out, base + ".wav")
                if os.path.abspath(cur) != os.path.abspath(final_wav):
                    shutil.move(cur, final_wav)
                    if cur in temps:
                        temps.remove(cur)
                print(f"   ✓ {os.path.basename(final_wav)} (обработано; добавь --flac/--alac для lossless)")
            else:
                tag_mp3(mp3_path, title, artist, cover, cover_mime, lyrics=plain_lyrics)
                print(f"   ✓ {os.path.basename(mp3_path)}")
        _cleanup(temps)
        ok += 1

    print(f"\nГотово: {ok}/{len(tracks)} в папке {out}")
    print("Импорт в Apple Music: File → Import…  (или перетащи папку в окно приложения)")


if __name__ == "__main__":
    main()
