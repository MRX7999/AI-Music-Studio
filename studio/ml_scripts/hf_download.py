"""Hugging Face model download with progress, executed with the Python of a tool's own environment
(mflux brings huggingface_hub and hf_xet). The engine never imports huggingface_hub itself.

Why not let the tool download on first use: huggingface_hub 1.x writes every attempt into a new
`<blob>.<random>.incomplete` file and cannot continue it, so an interrupted multi-gigabyte download
leaves dead partial files behind and the tool fails with an incomplete snapshot. This script

  * removes this repo's unfinished files from earlier attempts (older than --stale-minutes),
  * checks free disk space against what is still missing,
  * downloads the snapshot (retrying network errors) and prints one progress line per second:
        @progress 41.2 Z-Image Turbo: 2.43 of 5.91 GB · 5.3 MB/s · ~11 min left
  * deletes its own partial files when it is cancelled (SIGTERM / SIGINT).

usage: python hf_download.py REPO [--revision R] [--label TEXT] [--stale-minutes 15]
exit codes: 0 done, 2 no connection, 3 not enough disk space, 1 any other error
"""
import argparse
import fnmatch
import os
import shutil
import signal
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")
os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "30")
os.environ.pop("HF_HUB_OFFLINE", None)

IGNORE = ["*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", ".DS_Store"]
GB = 1e9
RETRY_WAIT = float(os.environ.get("AMS_HF_RETRY_WAIT", "10"))

_NET_CLASSES = {"ConnectError", "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout", "TimeoutException",
                "NetworkError", "RemoteProtocolError", "ProxyError", "ReadError", "LocalEntryNotFoundError",
                "OfflineModeIsEnabled", "ConnectionError", "Timeout", "TimeoutError", "ConnectionResetError",
                "ConnectionRefusedError", "gaierror"}
_NET_WORDS = ("nodename nor servname", "name or service not known", "temporary failure in name resolution",
              "failed to lookup address", "dns error", "network is unreachable", "connection refused",
              "connection reset", "timed out", "error sending request", "cannot reach", "no route to host",
              "connecterror", "offline mode")


def is_network_error(exc: BaseException) -> bool:
    seen = set()
    e = exc
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        if type(e).__name__ in _NET_CLASSES:
            return True
        if any(w in str(e).lower() for w in _NET_WORDS):
            return True
        e = e.__cause__ or e.__context__
    return False


def mflux_revision(repo: str):
    """The revision mflux pins for this repo (None → main), so mflux finds the snapshot later."""
    try:
        from mflux.models.common.resolution.model_revisions import ModelRevisions
        return ModelRevisions.get(repo)
    except Exception:
        return None


def ignored(name: str) -> bool:
    return any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(Path(name).name, p) for p in IGNORE)


def blob_name(sibling) -> str:
    """Cache blob name of a repo file: sha256 for LFS/Xet files, git blob id for small ones."""
    lfs = getattr(sibling, "lfs", None)
    sha = None
    if isinstance(lfs, dict):
        sha = lfs.get("sha256")
    elif lfs is not None:
        sha = getattr(lfs, "sha256", None)
    return sha or getattr(sibling, "blob_id", None) or ""


def file_size(sibling) -> int:
    size = getattr(sibling, "size", None)
    if not size:
        lfs = getattr(sibling, "lfs", None)
        size = lfs.get("size") if isinstance(lfs, dict) else getattr(lfs, "size", None)
    return int(size or 0)


def clean_stale(blobs: Path, minutes: float) -> int:
    """Delete `*.incomplete` leftovers of earlier attempts; returns bytes freed."""
    freed = 0
    if not blobs.is_dir():
        return 0
    limit = time.time() - minutes * 60
    for f in blobs.iterdir():
        if not f.name.endswith(".incomplete"):
            continue
        try:
            st = f.stat()
            if st.st_mtime < limit:
                f.unlink()
                freed += st.st_size
        except OSError:
            pass
    return freed


def fmt_eta(seconds: float) -> str:
    if seconds < 90:
        return f"~{max(1, int(seconds))} s left"
    if seconds < 5400:
        return f"~{int(round(seconds / 60))} min left"
    return f"~{seconds / 3600:.1f} h left"


class Progress(threading.Thread):
    """Polls the cache: finished blobs of this snapshot + partial files this process created."""

    def __init__(self, blobs: Path, files: list, total: int, label: str, before: set):
        super().__init__(daemon=True)
        self.blobs, self.files, self.total, self.label, self.before = blobs, files, total, label, before
        self.stop = threading.Event()
        self.samples: list[tuple[float, int]] = []

    def measure(self) -> int:
        done = 0
        for _, blob, size in self.files:
            if blob and (self.blobs / blob).exists():
                done += size
        try:
            for f in self.blobs.iterdir():
                if f.name.endswith(".incomplete") and f.name not in self.before:
                    try:
                        done += f.stat().st_size
                    except OSError:
                        pass
        except OSError:
            pass
        return min(done, self.total)

    def line(self) -> str:
        cur = self.measure()
        now = time.time()
        self.samples = [s for s in self.samples if now - s[0] <= 15] + [(now, cur)]
        text = f"{self.label}: {cur / GB:.2f} of {self.total / GB:.2f} GB"
        t_first, b_first = self.samples[0]
        if now - t_first >= 3 and cur > b_first:
            speed = (cur - b_first) / (now - t_first)
            text += f" · {speed / 1e6:.1f} MB/s · {fmt_eta((self.total - cur) / speed)}"
        pct = 100.0 * cur / self.total if self.total else 0.0
        return f"@progress {min(pct, 99.9):.1f} {text}"

    def run(self):
        while not self.stop.wait(1.0):
            print(self.line(), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--revision", default=None)
    ap.add_argument("--label", default="")
    ap.add_argument("--stale-minutes", type=float, default=15.0)
    a = ap.parse_args()
    label = a.label or a.repo.split("/")[-1]

    from huggingface_hub import HfApi, snapshot_download
    from huggingface_hub.constants import HF_HUB_CACHE

    revision = a.revision or mflux_revision(a.repo)
    cache = Path(HF_HUB_CACHE)
    blobs = cache / ("models--" + a.repo.replace("/", "--")) / "blobs"

    freed = clean_stale(blobs, a.stale_minutes)
    if freed:
        print(f"Removed unfinished files of earlier download attempts: {freed / GB:.2f} GB", flush=True)

    try:
        info = HfApi().model_info(a.repo, revision=revision, files_metadata=True)
    except Exception as e:  # noqa: BLE001 — reported to the user as text
        if is_network_error(e):
            print(f"ERROR no connection to huggingface.co: {type(e).__name__}: {e}", flush=True)
            return 2
        print(f"ERROR {type(e).__name__}: {e}", flush=True)
        return 1

    files = [(s.rfilename, blob_name(s), file_size(s)) for s in (info.siblings or []) if not ignored(s.rfilename)]
    total = sum(f[2] for f in files) or 1
    have = sum(size for _, blob, size in files if blob and (blobs / blob).exists())
    need = max(0, total - have)
    probe = cache if cache.exists() else cache.parent if cache.parent.exists() else Path.home()
    free = shutil.disk_usage(probe).free
    if need and free < need + 512 * 1024 * 1024:
        print(f"ERROR not enough disk space: {need / GB:.2f} GB to download, {free / GB:.2f} GB free", flush=True)
        return 3
    print(f"{label}: {total / GB:.2f} GB in total, {have / GB:.2f} GB already downloaded, "
          f"{need / GB:.2f} GB to go", flush=True)

    before = {f.name for f in blobs.iterdir()} if blobs.is_dir() else set()

    def on_signal(signum, _frame):
        # partial files of this process are useless to the next attempt: remove them
        try:
            for f in blobs.iterdir():
                if f.name.endswith(".incomplete") and f.name not in before:
                    try:
                        f.unlink()
                    except OSError:
                        pass
        except OSError:
            pass
        print("Cancelled", flush=True)
        os._exit(128 + signum)

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    bar = Progress(blobs, files, total, label, before)
    bar.start()
    try:
        for attempt in range(3):
            try:
                path = snapshot_download(a.repo, revision=revision, ignore_patterns=IGNORE)
                break
            except Exception as e:  # noqa: BLE001
                net = is_network_error(e)
                if net and attempt < 2:
                    wait = RETRY_WAIT * (attempt + 1)
                    print(f"Connection problem ({type(e).__name__}), retrying in {wait} s", flush=True)
                    time.sleep(wait)
                    continue
                if net:
                    print(f"ERROR no connection to huggingface.co: {type(e).__name__}: {e}", flush=True)
                    return 2
                if "no space left" in str(e).lower():
                    print(f"ERROR not enough disk space: {e}", flush=True)
                    return 3
                print(f"ERROR {type(e).__name__}: {e}", flush=True)
                return 1
    finally:
        bar.stop.set()
    print(f"@progress 100 {label}: downloaded", flush=True)
    print(f"SNAPSHOT {path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
