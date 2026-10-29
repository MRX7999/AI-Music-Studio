"""Хранение API-ключа: переменная окружения → Связка ключей macOS → только память сессии.

Ключ никогда не передаётся аргументом командной строки: в Keychain он пишется через
`security -i`, команда подаётся в stdin.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

SERVICE = "ai-music-studio"


def _has_keychain() -> bool:
    return sys.platform == "darwin" and shutil.which("security") is not None


def get_secret(account: str, env: str) -> tuple[str, str]:
    """→ (значение, источник)."""
    v = os.environ.get(env, "")
    if v:
        return v, f"переменная {env}"
    if _has_keychain():
        r = subprocess.run(["security", "find-generic-password", "-s", SERVICE, "-a", account, "-w"],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip(), "Связка ключей macOS"
    return "", ""


def save_secret(account: str, value: str) -> bool:
    if not _has_keychain() or not value:
        return False
    esc = value.replace("\\", "\\\\").replace('"', '\\"')
    cmd = f'add-generic-password -U -s {SERVICE} -a {account} -w "{esc}"\n'
    r = subprocess.run(["security", "-i"], input=cmd, capture_output=True, text=True)
    return r.returncode == 0


def delete_secret(account: str) -> bool:
    if not _has_keychain():
        return False
    r = subprocess.run(["security", "delete-generic-password", "-s", SERVICE, "-a", account],
                       capture_output=True, text=True)
    return r.returncode == 0
