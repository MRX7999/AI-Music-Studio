"""Telegram Bot API: sendAudio to a channel or chat (https://core.telegram.org/bots/api#sendaudio).

Limits: MP3/M4A to appear in the music player, files up to 50 MB through the public Bot API,
caption up to 1024 characters, thumbnail JPEG ≤ 200 kB and ≤ 320 px.
The bot must be an administrator of the channel. The token is kept in Keychain by the app
(or TELEGRAM_BOT_TOKEN in .env) and is only sent to api.telegram.org.
"""
from __future__ import annotations

import html
import time
from pathlib import Path

import requests

API = "https://api.telegram.org"
MAX_BYTES = 50 * 1024 * 1024
MAX_CAPTION = 1024


class TelegramError(RuntimeError):
    def __init__(self, msg: str, retry_after: float | None = None, permanent: bool = False):
        super().__init__(msg)
        self.retry_after = retry_after
        self.permanent = permanent


def _call(token: str, method: str, session=None, files=None, timeout: float = 60, **params):
    s = session or requests
    try:
        r = s.post(f"{API}/bot{token}/{method}", data=params, files=files, timeout=timeout)
    except requests.RequestException as e:
        raise TelegramError(f"Telegram: network error {e.__class__.__name__}") from None
    try:
        j = r.json()
    except ValueError:
        raise TelegramError(f"Telegram: HTTP {r.status_code}") from None
    if not j.get("ok"):
        ra = (j.get("parameters") or {}).get("retry_after")
        code = j.get("error_code")
        raise TelegramError(f"Telegram {method}: {j.get('description')}", retry_after=ra,
                            permanent=code in (400, 401, 403, 404))
    return j["result"]


def check(token: str, chat_id: str, session=None) -> dict:
    me = _call(token, "getMe", session)
    chat = _call(token, "getChat", session, chat_id=chat_id)
    return {"bot": me.get("username"), "chat_title": chat.get("title") or chat.get("username") or str(chat_id),
            "chat_username": chat.get("username") or "", "chat_type": chat.get("type")}


def build_caption(title: str, artist: str, text: str = "", ai_note: str = "", tags: list[str] | None = None) -> str:
    """HTML caption ≤ 1024 chars. Only the free text is shortened: title, tags and the AI note stay."""
    head = f"<b>{html.escape(artist)} — {html.escape(title)}</b>" if artist else f"<b>{html.escape(title)}</b>"
    tail = []
    if tags:
        tail.append(" ".join("#" + "".join(ch for ch in t if ch.isalnum() or ch == "_") for t in tags if t))
    if ai_note:
        tail.append(f"<i>{html.escape(ai_note)}</i>")
    fixed = "\n\n".join([head] + tail)
    body = text.strip()
    if body:
        budget = MAX_CAPTION - len(fixed) - 2
        esc = html.escape(body)
        if len(esc) > budget:
            # shorten the raw text so that no HTML entity is cut in half
            raw = body[: max(0, int(len(body) * budget / (len(esc) + 1)))]
            while raw and len(html.escape(raw)) + 1 > budget:
                raw = raw[:-1]
            esc = html.escape(raw.rstrip()) + "…" if raw.strip() else ""
        if esc:
            return "\n\n".join([head, esc] + tail)
    return fixed[:MAX_CAPTION]


def send_audio(token: str, chat_id: str, audio: str | Path, title: str, performer: str = "",
               duration: int | None = None, caption: str = "", thumb: str | Path | None = None,
               silent: bool = False, session=None, confirmed: bool = False, retries: int = 3) -> dict:
    if not confirmed:
        raise PermissionError("Publishing requires confirmation in the app")
    audio = Path(audio)
    if audio.suffix.lower() not in (".mp3", ".m4a"):
        raise TelegramError("Telegram music player needs MP3 or M4A", permanent=True)
    if audio.stat().st_size > MAX_BYTES:
        raise TelegramError(f"File is {audio.stat().st_size / 1e6:.1f} MB, Bot API limit is 50 MB", permanent=True)
    params = {"chat_id": chat_id, "title": title[:64], "performer": performer[:64], "caption": caption,
              "parse_mode": "HTML", "disable_notification": "true" if silent else "false"}
    if duration:
        params["duration"] = str(int(duration))
    last = None
    for attempt in range(retries):
        files = {"audio": (audio.name, open(audio, "rb"), "audio/mpeg" if audio.suffix == ".mp3" else "audio/mp4")}
        if thumb and Path(thumb).exists() and Path(thumb).stat().st_size <= 200 * 1024:
            files["thumbnail"] = (Path(thumb).name, open(thumb, "rb"), "image/jpeg")
        try:
            msg = _call(token, "sendAudio", session, files=files, timeout=600, **params)
            break
        except TelegramError as e:
            last = e
            if e.permanent or attempt == retries - 1:
                raise
            time.sleep(e.retry_after or (2 ** attempt * 3))
        finally:
            for f in files.values():
                f[1].close()
    else:
        raise last  # pragma: no cover
    chat = msg.get("chat") or {}
    username = chat.get("username")
    link = f"https://t.me/{username}/{msg['message_id']}" if username else ""
    return {"service": "telegram", "message_id": msg["message_id"], "chat_id": chat.get("id"), "url": link}
