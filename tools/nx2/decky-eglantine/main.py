# SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
# SPDX-License-Identifier: GPL-3.0-or-later
"""Decky backend. The ini logic and its tests are in py_modules/eglantine_ini.py."""
import asyncio
import os

import decky
import eglantine_ini as ini
import eglantine_update as builds

CONFIG_DIR = os.path.join(decky.DECKY_USER_HOME, ".config", "eden")
APP_DIR = os.path.join(decky.DECKY_USER_HOME, "Applications")
DATA_DIR = os.path.join(decky.DECKY_USER_HOME, ".local", "share", "eden")
LOG_PATH = os.path.join(DATA_DIR, "log", "eden_log.txt")
LOSSLESS_DLL = os.path.join(DATA_DIR, "lossless", "Lossless.dll")


def _state(scope, error=None):
    state = ini.get_state(
        CONFIG_DIR, scope, ini.emulator_running(), ini.read_last_game(LOG_PATH)
    )
    state["lsfg_ready"] = os.path.exists(LOSSLESS_DLL)
    state["error"] = error
    return state


def _run(scope, action):
    """Run a write and return the new state. A failed write goes to the panel as text."""
    try:
        action()
    except ini.Refused as e:
        return _state(scope, str(e))
    except OSError as e:
        decky.logger.error(f"write failed: {e}")
        return _state(scope, f"No se pudo escribir: {e}")
    return _state(scope)


def _change_build(action):
    """Run a change of build and return the new state. A failure goes to the panel as text."""
    error = None
    try:
        action()
    except ini.Refused as e:
        error = str(e)
    except builds.ERRORS as e:
        decky.logger.error(f"build change failed: {e}")
        error = f"No se pudo cambiar de build: {e}"
    state = builds.check(APP_DIR)
    if error:
        state["error"] = error
    return state


class Plugin:
    async def get_state(self, scope):
        return _state(scope)

    async def set_setting(self, scope, key, value):
        return _run(
            scope,
            lambda: ini.apply_changes(CONFIG_DIR, scope, {key: value}, ini.emulator_running()),
        )

    async def apply_preset(self, scope, preset_id):
        return _run(
            scope,
            lambda: ini.apply_preset(CONFIG_DIR, scope, preset_id, ini.emulator_running()),
        )

    # These use a thread, because a download takes minutes and the panel polls during that time.
    async def check_build(self):
        return await asyncio.to_thread(builds.check, APP_DIR)

    async def update_build(self):
        return await asyncio.to_thread(
            _change_build, lambda: builds.update(APP_DIR, ini.emulator_running)
        )

    async def rollback_build(self):
        return await asyncio.to_thread(
            _change_build, lambda: builds.rollback(APP_DIR, ini.emulator_running)
        )

    async def _main(self):
        decky.logger.info(f"config folder: {CONFIG_DIR}")

    async def _unload(self):
        pass
