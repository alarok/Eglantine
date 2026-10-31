# SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read and edit the Eglantine config files for the Decky panel.

The rules come from src/frontend_common/config.cpp:
- A global value has the lines "key\\default=false" and "key=value".
- "key\\default=true" tells the emulator to use its built-in default. It ignores the value line.
- A game value also has "key\\use_global=false". "key\\use_global=true" takes the global value.

This code always writes "key\\default=false" with a value. It does not compare with a default,
because the built-in defaults change between builds.

The emulator reads and writes the global file at start, at each boot and at exit. It reads and
writes a game file at the boot of that game and in the per-game dialog. See main_window.cpp.
"""
import os
import re
import shutil

BACKUP_SUFFIX = ".decky-bak"
TEMP_SUFFIX = ".decky-tmp"
GLOBAL_SCOPE = "global"
INHERIT = "inherit"
LOG_HEAD_BYTES = 1024 * 1024

TITLE_RE = re.compile(r"^[0-9A-F]{16}$")
LOADING_RE = re.compile(r"Loading (.+) \(([0-9A-Fa-f]{16})\) \.\.\.")
EMULATOR_EXES = {"eglantine", "eden", "yuzu"}

KNOWN_TITLES = {
    "040074A01BF12000": "Donkey Kong Bananza",
    "0400C3F00006E000": "Mario Kart World",
    "0400A3A01EE4C000": "Pokopia",
}

# Enum numbers come from src/common/settings_enums.h. Words on the panel are for the owner's
# console, which uses Spanish. "Fast" and "Accurate" are the words of the emulator GUI.
SETTINGS = [
    {
        "key": "resolution_setup",
        "section": "Renderer",
        "label": "Resolución",
        "options": [
            ("0", "0.25x"), ("1", "0.5x"), ("2", "0.75x"), ("3", "1x"), ("4", "1.25x"),
            ("5", "1.5x"), ("6", "2x"), ("7", "3x"), ("8", "4x"), ("9", "5x"),
            ("10", "6x"), ("11", "7x"), ("12", "8x"),
        ],
    },
    {
        "key": "scaling_filter",
        "section": "Renderer",
        "label": "Filtro",
        "options": [
            ("15", "FSR 3"), ("6", "FSR 1"), ("1", "Bilinear"), ("0", "Nearest"), ("2", "Bicubic"),
            ("3", "Gaussian"), ("4", "Lanczos"), ("5", "ScaleForce"), ("7", "Area"),
            ("8", "Zero-Tangent"), ("9", "B-Spline"), ("10", "Mitchell"), ("11", "Spline-1"),
            ("12", "MMPX"), ("13", "SGSR"), ("14", "SGSR EdgeDir"),
        ],
    },
    {
        "key": "gpu_accuracy",
        "section": "Renderer",
        "label": "Modo GPU",
        "options": [("0", "Fast"), ("1", "Accurate")],
    },
    {
        "key": "use_docked_mode",
        "section": "System",
        "label": "Consola",
        "options": [("0", "Portátil"), ("1", "Dock")],
    },
    {
        "key": "frame_gen",
        "section": "Renderer",
        "label": "Generar fotogramas",
        "options": [("false", "No"), ("true", "Sí")],
    },
    {
        "key": "frame_gen_multiplier",
        "section": "Renderer",
        "label": "Multiplicador",
        "options": [("2", "x2"), ("3", "x3"), ("4", "x4")],
    },
    {
        "key": "frame_gen_type",
        "section": "Renderer",
        "label": "Tipo",
        "options": [("1", "FSR 3"), ("0", "LSFG")],
    },
    {
        "key": "dma_accuracy",
        "section": "Renderer",
        "label": "DMA",
        "options": [("0", "Default"), ("1", "Unsafe"), ("2", "Safe")],
        "hidden": True,
    },
]
SETTINGS_BY_KEY = {s["key"]: s for s in SETTINGS}

PRESETS = [
    {
        "id": "speed",
        "label": "0.75x",
        "values": {
            "resolution_setup": "2", "scaling_filter": "15", "gpu_accuracy": "0", "frame_gen": "false",
        },
    },
    {
        "id": "native",
        "label": "1x",
        "values": {
            "resolution_setup": "3", "scaling_filter": "15", "gpu_accuracy": "0", "frame_gen": "false",
        },
    },
    {
        "id": "frame_gen",
        "label": "0.75x FG",
        "values": {
            "resolution_setup": "2", "scaling_filter": "15", "gpu_accuracy": "0", "frame_gen": "true",
            "frame_gen_multiplier": "2", "frame_gen_type": "1",
        },
    },
]


class Refused(Exception):
    """The request cannot run. The text goes to the panel."""


def _is_header(line):
    return line.startswith("[") and line.rstrip().endswith("]")


def _edit_section(text, section, drop, new_lines):
    """Remove the lines named in drop and put new_lines at the first removed place.

    Lines outside the named section stay byte for byte. With no removed line, new_lines go at
    the end of the section, before its blank lines.
    """
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(newline)
    header = f"[{section}]"
    start = next((i for i, line in enumerate(lines) if line.strip() == header), None)
    if start is None:
        lead = text
        if lead and not lead.endswith(newline):
            lead += newline
        if lead:
            lead += newline
        return lead + newline.join([header, *new_lines]) + newline

    end = next((i for i in range(start + 1, len(lines)) if _is_header(lines[i])), len(lines))
    body = []
    place = None
    for line in lines[start + 1 : end]:
        if line.split("=", 1)[0] in drop:
            if place is None:
                place = len(body)
        else:
            body.append(line)
    if place is None:
        place = len(body)
        while place > 0 and not body[place - 1].strip():
            place -= 1
    body[place:place] = new_lines
    return newline.join(lines[: start + 1] + body + lines[end:])


def set_value(text, section, key, value, per_game):
    default = key + "\\default"
    use_global = key + "\\use_global"
    lines = [f"{default}=false", f"{key}={value}"]
    if per_game:
        lines.insert(0, f"{use_global}=false")
    return _edit_section(text, section, {key, default, use_global}, lines)


def set_inherit(text, section, key, per_game):
    default = key + "\\default"
    use_global = key + "\\use_global"
    if per_game:
        return _edit_section(text, section, {key, default, use_global}, [f"{use_global}=true"])
    return _edit_section(text, section, {default}, [f"{default}=true"])


def read_section(text, section):
    values = {}
    inside = False
    for line in text.splitlines():
        if _is_header(line):
            inside = line.strip() == f"[{section}]"
        elif inside and "=" in line:
            name, value = line.split("=", 1)
            values[name] = value
    return values


def read_global(values, key):
    """Return (selected, effective). A missing default line counts as default, as in config.cpp."""
    effective = values.get(key)
    if values.get(key + "\\default", "true") == "true":
        return INHERIT, effective
    return effective, effective


def read_game(game_values, global_values, key):
    if game_values.get(key + "\\use_global", "true") == "true":
        return INHERIT, read_global(global_values, key)[1]
    value = game_values.get(key)
    return value, value


def read_file(path):
    with open(path, newline="", encoding="utf-8", errors="surrogateescape") as f:
        return f.read()


def write_file(path, text):
    """Replace the file in one step. Keep a copy of the first text that this plugin found."""
    backup = path + BACKUP_SUFFIX
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
    temp = path + TEMP_SUFFIX
    try:
        with open(temp, "w", newline="", encoding="utf-8", errors="surrogateescape") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        shutil.copymode(path, temp)
        os.replace(temp, path)
    except BaseException:
        if os.path.exists(temp):
            os.unlink(temp)
        raise


def _global_path(config_dir):
    return os.path.join(config_dir, "qt-config.ini")


def _game_path(config_dir, title):
    return os.path.join(config_dir, "custom", title + ".ini")


def _scope_path(config_dir, scope):
    if scope == GLOBAL_SCOPE:
        path = _global_path(config_dir)
    elif TITLE_RE.match(scope):
        path = _game_path(config_dir, scope)
    else:
        raise Refused(f"Ámbito no válido: {scope}")
    if not os.path.isfile(path):
        raise Refused(f"No existe {path}. Arranca el juego una vez en Eglantine.")
    return path


def list_titles(config_dir, last_game=None):
    names = dict(KNOWN_TITLES)
    # A loose dump logs "Unknown program". A known name is better than this.
    if last_game and last_game[1] != "Unknown program":
        names.setdefault(last_game[0], last_game[1])
    try:
        files = os.listdir(os.path.join(config_dir, "custom"))
    except OSError:
        files = []
    titles = [f[:-4] for f in files if f.endswith(".ini") and TITLE_RE.match(f[:-4])]
    return sorted(
        ({"id": t, "name": names.get(t, t)} for t in titles), key=lambda t: t["name"].lower()
    )


def get_state(config_dir, scope, running, last_game=None):
    """Return all that the panel shows. An empty scope selects the last game, or global."""
    titles = list_titles(config_dir, last_game)
    title_ids = {t["id"] for t in titles}
    if not scope:
        scope = last_game[0] if last_game and last_game[0] in title_ids else GLOBAL_SCOPE
    elif scope != GLOBAL_SCOPE and scope not in title_ids:
        scope = GLOBAL_SCOPE

    global_path = _global_path(config_dir)
    found = os.path.isfile(global_path)
    global_text = read_file(global_path) if found else ""
    game_text = "" if scope == GLOBAL_SCOPE else read_file(_game_path(config_dir, scope))

    settings = []
    dma = None
    for setting in SETTINGS:
        key = setting["key"]
        global_values = read_section(global_text, setting["section"])
        if scope == GLOBAL_SCOPE:
            selected, effective = read_global(global_values, key)
        else:
            game_values = read_section(game_text, setting["section"])
            selected, effective = read_game(game_values, global_values, key)
        if key == "dma_accuracy":
            dma = effective
        if setting.get("hidden"):
            continue

        labels = dict(setting["options"])
        options = [{"value": v, "label": label} for v, label in setting["options"]]
        if selected not in labels and selected != INHERIT:
            options.append({"value": selected, "label": str(selected)})
        inherit = "Por defecto" if scope == GLOBAL_SCOPE else "Global"
        if effective is not None:
            inherit += f" ({labels.get(effective, effective)})"
        options.insert(0, {"value": INHERIT, "label": inherit})
        settings.append(
            {
                "key": key,
                "label": setting["label"],
                "options": options,
                "selected": selected,
                "effective": effective,
            }
        )
    return {
        "found": found,
        "scope": scope,
        "running": running,
        "titles": titles,
        "last_game": last_game[0] if last_game else None,
        "settings": settings,
        "dma": dma,
        "presets": [{"id": p["id"], "label": p["label"]} for p in PRESETS],
    }


def apply_changes(config_dir, scope, changes, running):
    """Check all changes, then write the file of the scope once."""
    per_game = scope != GLOBAL_SCOPE
    for key, value in changes.items():
        setting = SETTINGS_BY_KEY.get(key)
        if setting is None:
            raise Refused(f"Ajuste no válido: {key}")
        if value != INHERIT and value not in dict(setting["options"]):
            raise Refused(f"Valor no válido para {key}: {value!r}")
    path = _scope_path(config_dir, scope)
    if not per_game and running:
        raise Refused("Eglantine está abierto. Ciérralo para cambiar los ajustes globales.")

    old_text = read_file(path)
    text = old_text
    for key, value in changes.items():
        section = SETTINGS_BY_KEY[key]["section"]
        if value == INHERIT:
            text = set_inherit(text, section, key, per_game)
        else:
            text = set_value(text, section, key, value, per_game)
    if text != old_text:
        write_file(path, text)


def apply_preset(config_dir, scope, preset_id, running):
    preset = next((p for p in PRESETS if p["id"] == preset_id), None)
    if preset is None:
        raise Refused(f"Preset no válido: {preset_id}")
    apply_changes(config_dir, scope, preset["values"], running)


def last_loaded_title(log_text):
    """Return (title id, game name) from the last "Loading" line of core.cpp, or None."""
    matches = LOADING_RE.findall(log_text)
    if not matches:
        return None
    name, title = matches[-1]
    return title.upper(), name


def read_last_game(log_path):
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            return last_loaded_title(f.read(LOG_HEAD_BYTES))
    except OSError:
        return None


def is_emulator_exe(exe_path):
    name = exe_path.removesuffix(" (deleted)").rsplit("/", 1)[-1]
    return name in EMULATOR_EXES


def emulator_running(proc_root="/proc"):
    """Look at the binary of each process. A plugin process can have the emulator name in its title."""
    try:
        pids = [p for p in os.listdir(proc_root) if p.isdigit()]
    except OSError:
        return False
    for pid in pids:
        try:
            if is_emulator_exe(os.readlink(os.path.join(proc_root, pid, "exe"))):
                return True
        except OSError:
            continue
    return False
