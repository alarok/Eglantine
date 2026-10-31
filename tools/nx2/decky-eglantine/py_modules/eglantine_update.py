# SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
# SPDX-License-Identifier: GPL-3.0-or-later
"""Find, download and select the Eglantine build that the launch scripts start.

The scripts in ~/Applications start a build by its file name. A change of build replaces only that
name in each script. Old builds stay on the disk. This module does not touch a settings file.

Only a panel button starts a download or a change. A check at panel open reads the release list.
"""
import glob
import hashlib
import http.client
import json
import os
import re
import ssl
import stat
import threading
import urllib.request

from eglantine_ini import Refused

RELEASES_URL = "https://api.github.com/repos/alarok/Eglantine/releases?per_page=30"
DOWNLOAD_PREFIX = "https://github.com/alarok/Eglantine/releases/download/"
TAG = re.compile(r"build-(\d+)")
ASSET = re.compile(r"eglantine-[0-9a-f]+-linux-x86_64-steamdeck-pgo\.AppImage")
DIGEST = re.compile(r"sha256:([0-9a-f]{64})")
# Test tools find the running process with this name, so keep it.
LOCAL_NAME = "eglantine-build{}-steamdeck-pgo.AppImage"
LOCAL = re.compile(r"eglantine-build(\d+)-steamdeck-pgo\.AppImage")
# Decky runs a frozen Python. Its default certificate path does not have to be the system path.
CA_FILE = "/etc/ssl/certs/ca-certificates.crt"
TIMEOUT_S = 30
CHUNK = 1 << 20
TEMP_SUFFIX = ".decky-tmp"
CLOSE_FIRST = "Eglantine está abierto. Ciérralo para cambiar de build."

# The errors of a network or disk failure. The caller shows them to the person as text.
ERRORS = (OSError, ValueError, http.client.HTTPException)

_busy = threading.Lock()


def _open(url):
    request = urllib.request.Request(url, headers={"User-Agent": "decky-eglantine"})
    context = ssl.create_default_context(cafile=CA_FILE if os.path.exists(CA_FILE) else None)
    return urllib.request.urlopen(request, timeout=TIMEOUT_S, context=context)


def latest_release(releases):
    """Return the highest usable build-N. Builds are prereleases, so a prerelease counts."""
    if not isinstance(releases, list):
        raise ValueError("the release list has an unknown form")
    best = None
    for release in releases:
        tag = TAG.fullmatch(release.get("tag_name", ""))
        if not tag or release.get("draft"):
            continue
        build = int(tag.group(1))
        if best and build <= best["build"]:
            continue
        for asset in release.get("assets", []):
            digest = DIGEST.fullmatch(asset.get("digest") or "")
            url = asset.get("browser_download_url", "")
            if digest and ASSET.fullmatch(asset.get("name", "")) and url.startswith(DOWNLOAD_PREFIX):
                best = {"build": build, "url": url, "sha256": digest.group(1)}
    return best


def _fetch_latest(opener):
    with opener(RELEASES_URL) as response:
        return latest_release(json.load(response))


def _read_text(path):
    with open(path, encoding="utf-8", errors="surrogateescape", newline="") as f:
        return f.read()


def _scripts(app_dir):
    """Return {script path: build} for each script that names a build."""
    found = {}
    for path in sorted(glob.glob(os.path.join(glob.escape(app_dir), "*.sh"))):
        builds = [int(n) for n in LOCAL.findall(_read_text(path))]
        if builds:
            found[path] = max(builds)
    return found


def _previous(app_dir, scripts):
    current = max(scripts.values())
    local = [m for m in map(LOCAL.fullmatch, os.listdir(app_dir)) if m]
    lower = [int(m.group(1)) for m in local if int(m.group(1)) < current]
    return max(lower, default=None)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _download(release, app_dir, opener):
    """Put the build on the disk. The final name appears only after the digest check."""
    target = os.path.join(app_dir, LOCAL_NAME.format(release["build"]))
    if os.path.exists(target) and _sha256(target) == release["sha256"]:
        return
    temp = target + TEMP_SUFFIX
    digest = hashlib.sha256()
    try:
        with opener(release["url"]) as response, open(temp, "wb") as out:
            while chunk := response.read(CHUNK):
                out.write(chunk)
                digest.update(chunk)
            out.flush()
            os.fsync(out.fileno())
        if digest.hexdigest() != release["sha256"]:
            raise Refused(f"La build {release['build']} no coincide con su SHA-256. No cambio nada.")
        os.chmod(temp, 0o755)
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.remove(temp)


def _select(app_dir, scripts, build):
    """Make each script start the build. Each script changes in one step."""
    name = LOCAL_NAME.format(build)
    for path in scripts:
        text = _read_text(path)
        changed = LOCAL.sub(name, text)
        if changed == text:
            continue
        temp = path + TEMP_SUFFIX
        try:
            with open(temp, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
                f.write(changed)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(temp, stat.S_IMODE(os.stat(path).st_mode))
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.remove(temp)


def _guarded(app_dir, is_running, action):
    if not _busy.acquire(blocking=False):
        raise Refused("Ya hay un cambio de build en marcha.")
    try:
        if is_running():
            raise Refused(CLOSE_FIRST)
        scripts = _scripts(app_dir)
        if not scripts:
            raise Refused("No hay scripts de arranque en ~/Applications.")
        action(scripts)
    finally:
        _busy.release()


def update(app_dir, is_running, opener=_open):
    """Download the latest build and select it."""

    def action(scripts):
        release = _fetch_latest(opener)
        if release is None or release["build"] <= max(scripts.values()):
            raise Refused("No hay una build más nueva.")
        _download(release, app_dir, opener)
        # A download takes minutes, and a game can start in that time.
        if is_running():
            raise Refused(f"Build {release['build']} descargada. {CLOSE_FIRST}")
        _select(app_dir, scripts, release["build"])

    _guarded(app_dir, is_running, action)


def rollback(app_dir, is_running):
    """Select the highest build on the disk that is lower than the current build."""

    def action(scripts):
        previous = _previous(app_dir, scripts)
        if previous is None:
            raise Refused("No hay una build anterior en ~/Applications.")
        _select(app_dir, scripts, previous)

    _guarded(app_dir, is_running, action)


def check(app_dir, opener=_open):
    """Return the state for the panel. During a change, this does not use the network."""
    scripts = _scripts(app_dir)
    if not scripts:
        return {"available": False}
    current = sorted(set(scripts.values()))
    state = {
        "available": True,
        "busy": _busy.locked(),
        "current": current,
        "latest": None,
        "update": False,
        "previous": _previous(app_dir, scripts),
        "error": None,
    }
    if state["busy"]:
        return state
    try:
        release = _fetch_latest(opener)
    except ERRORS as e:
        state["error"] = f"No se pudo mirar GitHub: {e}"
        return state
    if release:
        state["latest"] = release["build"]
        state["update"] = release["build"] > current[-1]
    return state
