"""YouTube Data API v3 upload with OAuth 2.0 for installed apps (loopback + PKCE).

* The user creates an OAuth client of type "Desktop app" in their own Google Cloud project and
  enters the client id/secret in the app (Keychain) or YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET.
  While the consent screen is in "Testing" mode Google expires refresh tokens after 7 days.
* videos.insert uses its own quota bucket; uploads are resumable (8 MB chunks, retried).
* `status.containsSyntheticMedia` is the AI disclosure flag; it is set from the project.
* Default visibility is private; `publishAt` schedules a private video to go public.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import threading
import time
import urllib.parse
from pathlib import Path

import requests

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
API = "https://www.googleapis.com/youtube/v3"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
CHUNK = 8 * 1024 * 1024
MUSIC_CATEGORY = "10"
PRIVACY = ("private", "unlisted", "public")


class YouTubeError(RuntimeError):
    def __init__(self, msg: str, permanent: bool = False):
        super().__init__(msg)
        self.permanent = permanent


# --------------------------------------------------------------------------- OAuth

class _Handler(http.server.BaseHTTPRequestHandler):
    result: dict = {}

    def do_GET(self):  # noqa: N802
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        type(self).result = {k: v[0] for k, v in q.items()}
        ok = "code" in q
        body = ("<html><body style='font-family:-apple-system;padding:40px'><h2>"
                + ("AI Music Studio is connected to YouTube. You can close this tab." if ok else
                   "Authorization failed: " + (q.get("error", ["unknown"])[0]))
                + "</h2></body></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class LoopbackAuth:
    """Step 1: start() → URL for the system browser. Step 2: wait() → tokens."""

    def __init__(self, client_id: str, client_secret: str):
        self.client_id, self.client_secret = client_id, client_secret
        self.verifier = secrets.token_urlsafe(64)
        self.state = secrets.token_urlsafe(16)
        handler = type("H", (_Handler,), {"result": {}})
        self.server = http.server.HTTPServer(("127.0.0.1", 0), handler)
        self.handler = handler
        self.redirect = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = None

    def start(self) -> str:
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).rstrip(b"=").decode()
        q = {"client_id": self.client_id, "redirect_uri": self.redirect, "response_type": "code",
             "scope": SCOPES, "access_type": "offline", "prompt": "consent", "state": self.state,
             "code_challenge": challenge, "code_challenge_method": "S256"}
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        return AUTH_URL + "?" + urllib.parse.urlencode(q)

    def _serve(self):
        self.server.timeout = 1
        deadline = time.time() + 600
        while not self.handler.result and time.time() < deadline:
            self.server.handle_request()

    def wait(self, timeout: float = 600, cancel=None, session=None) -> dict:
        t0 = time.time()
        while not self.handler.result:
            if cancel and cancel():
                raise YouTubeError("Cancelled")
            if time.time() - t0 > timeout:
                raise YouTubeError("Authorization timeout")
            time.sleep(0.3)
        self.server.server_close()
        res = self.handler.result
        if res.get("state") != self.state:
            raise YouTubeError("OAuth state mismatch", permanent=True)
        if "code" not in res:
            raise YouTubeError("Authorization denied: " + res.get("error", "unknown"), permanent=True)
        s = session or requests
        r = s.post(TOKEN_URL, data={"code": res["code"], "client_id": self.client_id,
                                    "client_secret": self.client_secret, "redirect_uri": self.redirect,
                                    "grant_type": "authorization_code", "code_verifier": self.verifier}, timeout=30)
        j = r.json()
        if "refresh_token" not in j:
            raise YouTubeError(f"Token exchange failed: {j.get('error_description') or j}", permanent=True)
        return {"refresh_token": j["refresh_token"], "access_token": j.get("access_token"),
                "expires_in": j.get("expires_in")}


def access_token(client_id: str, client_secret: str, refresh_token: str, session=None) -> str:
    s = session or requests
    r = s.post(TOKEN_URL, data={"client_id": client_id, "client_secret": client_secret,
                                "refresh_token": refresh_token, "grant_type": "refresh_token"}, timeout=30)
    j = r.json()
    if "access_token" not in j:
        err = j.get("error")
        raise YouTubeError("YouTube authorization expired, connect again" if err == "invalid_grant"
                           else f"Token refresh failed: {j}", permanent=err == "invalid_grant")
    return j["access_token"]


def channel(token: str, session=None) -> dict:
    s = session or requests
    r = s.get(f"{API}/channels", params={"part": "snippet", "mine": "true"},
              headers={"Authorization": f"Bearer {token}"}, timeout=30)
    items = (r.json() or {}).get("items") or []
    if not items:
        raise YouTubeError("No YouTube channel on this Google account", permanent=True)
    return {"id": items[0]["id"], "title": items[0]["snippet"]["title"]}


# --------------------------------------------------------------------------- upload

def build_body(title: str, description: str = "", tags: list[str] | None = None, privacy: str = "private",
               publish_at: str = "", synthetic: bool = True, made_for_kids: bool = False,
               language: str = "") -> dict:
    if privacy not in PRIVACY:
        privacy = "private"
    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": bool(made_for_kids),
              "containsSyntheticMedia": bool(synthetic), "embeddable": True}
    if publish_at:
        status["privacyStatus"] = "private"        # API rule: scheduled videos are private until publishAt
        status["publishAt"] = publish_at
    snippet = {"title": title[:100], "description": description[:5000], "categoryId": MUSIC_CATEGORY,
               "tags": [t[:30] for t in (tags or []) if t][:30]}
    if language:
        snippet["defaultLanguage"] = language
        snippet["defaultAudioLanguage"] = language
    return {"snippet": snippet, "status": status}


def upload(video: str | Path, body: dict, client_id: str, client_secret: str, refresh_token: str,
           progress=None, cancel=None, session=None, confirmed: bool = False, confirm_public: bool = False) -> dict:
    if not confirmed:
        raise PermissionError("Publishing requires confirmation in the app")
    if body["status"].get("privacyStatus") == "public" and not confirm_public:
        raise PermissionError("Public visibility needs a separate confirmation")
    video = Path(video)
    s = session or requests
    token = access_token(client_id, client_secret, refresh_token, s)
    size = video.stat().st_size
    r = s.post(UPLOAD_URL, params={"uploadType": "resumable", "part": "snippet,status"},
               headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
                        "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
               data=json.dumps(body), timeout=60)
    if r.status_code >= 400:
        _raise(r)
    loc = r.headers.get("Location")
    if not loc:
        raise YouTubeError("No upload session URL")
    sent, fails = 0, 0
    with open(video, "rb") as fh:
        while sent < size:
            if cancel and cancel():
                raise YouTubeError("Cancelled")
            fh.seek(sent)
            chunk = fh.read(CHUNK)
            end = sent + len(chunk) - 1
            try:
                rr = s.put(loc, data=chunk, timeout=600,
                           headers={"Authorization": f"Bearer {token}", "Content-Length": str(len(chunk)),
                                    "Content-Range": f"bytes {sent}-{end}/{size}"})
            except requests.RequestException:
                rr = None
            if rr is not None and rr.status_code in (200, 201):
                vid = rr.json()["id"]
                if progress:
                    progress(1.0, "YouTube: uploaded")
                return {"service": "youtube", "video_id": vid, "url": f"https://youtu.be/{vid}",
                        "privacy": body["status"]["privacyStatus"], "publish_at": body["status"].get("publishAt", "")}
            if rr is not None and rr.status_code == 308:
                rng = rr.headers.get("Range")
                sent = int(rng.split("-")[1]) + 1 if rng else 0
                fails = 0
                if progress:
                    progress(0.05 + 0.9 * sent / size, f"YouTube: {sent / size * 100:.0f}%")
                continue
            if rr is not None and rr.status_code not in (500, 502, 503, 504):
                _raise(rr)
            fails += 1
            if fails > 6:
                raise YouTubeError("Upload failed after retries")
            time.sleep(min(60, 2 ** fails))
            q = s.put(loc, headers={"Authorization": f"Bearer {token}", "Content-Range": f"bytes */{size}"},
                      timeout=60)
            if q.status_code == 308:
                rng = q.headers.get("Range")
                sent = int(rng.split("-")[1]) + 1 if rng else 0
            elif q.status_code in (200, 201):
                vid = q.json()["id"]
                return {"service": "youtube", "video_id": vid, "url": f"https://youtu.be/{vid}",
                        "privacy": body["status"]["privacyStatus"], "publish_at": body["status"].get("publishAt", "")}
    raise YouTubeError("Upload ended without a video id")


def _raise(r):
    try:
        err = r.json().get("error") or {}
        reason = ((err.get("errors") or [{}])[0]).get("reason", "")
        msg = err.get("message") or r.text[:300]
    except ValueError:
        reason, msg = "", r.text[:300]
    permanent = r.status_code in (400, 401, 403) and reason not in ("rateLimitExceeded", "backendError")
    if reason in ("quotaExceeded", "uploadLimitExceeded"):
        msg = "YouTube daily upload limit reached, the queue will retry tomorrow"
        permanent = False
    raise YouTubeError(f"YouTube: {msg}", permanent=permanent)
