# SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
# SPDX-License-Identifier: GPL-3.0-or-later
"""Decky backend. The ini logic and its tests are in py_modules/eglantine_ini.py."""
import os

import decky
import eglantine_ini as ini

CONFIG_DIR = os.path.join(decky.DECKY_USER_HOME, ".config", "eden")
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

    async def _main(self):
        decky.logger.info(f"config folder: {CONFIG_DIR}")

    async def _unload(self):
        pass
