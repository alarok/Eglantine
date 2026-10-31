"""Run one game with several isolated profiles, one at a time, and collect the last frame of each.

Each variant changes one thing. The script copies key files without reading them.
A variant that needs files from a real profile gets the folder from an argument or an environment
variable. There is no default. The script never copies qt-config.ini or any other config file.

The child process gets this process's environment without the EDEN_NX2_* variables. To pass debug
variables to the emulator, set MATRIX_EXTRA_ENV="NAME=value;NAME=value".

Usage: python matrix.py --root <dir> --exe <eden-cli.exe> --game <exefs main> [--seconds N]
       [--keys-from <dir>] [--real-profile <dir>] [--firmware <dir>] [--nand-from <dir>] <variant> ...
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from PIL import Image, ImageDraw, ImageGrab

# Source folders. Each one comes from an argument or from the named environment variable.
SOURCES = {
    # key: (argument, environment variable, what the folder holds)
    "keys": ("--keys-from", "MATRIX_KEYS_FROM", "the folder with the key files"),
    "profile": ("--real-profile", "MATRIX_REAL_PROFILE", "the real profile folder (its nand and save are copied)"),
    "firmware": ("--firmware", "MATRIX_FIRMWARE", "the registered firmware folder"),
    "nand": ("--nand-from", "MATRIX_NAND_FROM", "the nand folder to copy"),
}
KEY_SCRIPT = "15:4,16:-4,25:4,26:-4,70:9,70:11,71:-9,71:-11,95:9,95:11,96:-9,96:-11,110:4,111:-4"
BASE = {
    "Core": {"memory_layout_mode": "4"},
    "Renderer": {"backend": "1", "gpu_accuracy": "1", "accelerate_astc": "1", "astc_recompression": "0",
                 "use_asynchronous_shaders": "false", "resolution_setup": "3", "frame_gen": "false"},
    "System": {"use_docked_mode": "1"},
    "Audio": {"audio_muted": "true", "volume": "0"},
    "Miscellaneous": {"log_filter": "*:Info Service.NS:Debug", "flush_line": "true"},
}
VARIANTS = {
    "base": {},
    "keys": {"keys": True},
    "lang": {"set": {"System": {"language_index": "5", "region_index": "2"}}},
    "acc0": {"set": {"Renderer": {"gpu_accuracy": "0"}}},
    "save": {"save": True},
    "fw": {"keys": True, "firmware": True},
    # The owner's non-default settings, in English, with the probe's forced ASTC and scale values removed.
    "mix": {"drop": {"Renderer": ["accelerate_astc", "astc_recompression", "resolution_setup"]},
            "set": {"Core": {"memory_layout_mode": "2"},
                    "Renderer": {"anti_aliasing": "1", "frame_pacing_mode": "4", "gpu_accuracy": "0",
                                 "gpu_unswizzle_stream_size": "4", "gpu_unswizzle_texture_size": "4",
                                 "scaling_filter": "15", "use_asynchronous_shaders": "true"},
                    "System": {"fast_cpu_time": "1"}}},
}
_renderer = VARIANTS["mix"]["set"]["Renderer"]
_system = VARIANTS["mix"]["set"]["System"]
_drop = VARIANTS["mix"]["drop"]
VARIANTS["mix2"] = {"drop": _drop, "set": {"Renderer": _renderer, "System": _system}}
VARIANTS["mix2-es"] = {"drop": _drop, "set": {"Renderer": _renderer,
                                              "System": {**_system, "language_index": "5", "region_index": "2"}}}
VARIANTS["async"] = {"set": {"Renderer": {"use_asynchronous_shaders": "true"}}}
VARIANTS["nand"] = {"nand": True}
VARIANTS["nand-es"] = {"nand": True, "set": {"System": {"language_index": "5", "region_index": "2"}}}
# "seed": the NAND a clean first boot left behind. "sysonly": the owner's profile without any game save.
# "nand_from": True takes the folder of --nand-from. "real" takes the nand folder of --real-profile.
VARIANTS["seed"] = {"nand_from": True}
VARIANTS["sysonly"] = {"nand_from": "real", "no_game_save": True}
_fs_log = {"Miscellaneous": {"log_filter": "*:Info Service.FS:Trace"}}
VARIANTS["fs1"] = {"set": _fs_log}
VARIANTS["fs2"] = {"set": _fs_log, "nand_from": True}
VARIANTS["seed-bananza"] = {"nand_from": True}
# The save from the owner's test profile: the game offers Continue and starts in the mine.
VARIANTS["seed-play"] = {"nand_from": True}
VARIANTS["seed-play-acc0"] = {"nand_from": True,
                              "set": {"Renderer": {"gpu_accuracy": "0"}}}
VARIANTS["win"] = {"visible": True}
VARIANTS["hand"] = {"set": {"System": {"use_docked_mode": "0"}}}
for _name, _section, _values in (
    ("s-layout", "Core", {"memory_layout_mode": "2"}),
    ("s-aa", "Renderer", {"anti_aliasing": "1"}),
    ("s-pace", "Renderer", {"frame_pacing_mode": "4"}),
    ("s-unswizzle", "Renderer", {"gpu_unswizzle_stream_size": "4", "gpu_unswizzle_texture_size": "4"}),
    ("s-scale", "Renderer", {"scaling_filter": "15"}),
    ("s-async", "Renderer", {"use_asynchronous_shaders": "true"}),
    ("s-fastcpu", "System", {"fast_cpu_time": "1"}),
):
    VARIANTS[_name] = {"set": {_section: _values}}
PATTERNS = ("aes_util", "QMD failed", "dispatch unsupported", "Unimplemented!", "shader rejected", "Draw skipped")


def grab_window(pid, path):
    """Save only the emulator's own window, so other desktop content stays out of the evidence."""
    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            found.append(((rect.right - rect.left) * (rect.bottom - rect.top), hwnd))
        return True

    user32.EnumWindows(visit, 0)
    if not found:
        return False
    hwnd = max(found)[1]
    # SetForegroundWindow is refused for a background process. A topmost window needs no focus.
    no_move_no_size_show = 0x0001 | 0x0002 | 0x0040
    user32.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, no_move_no_size_show)
    time.sleep(0.7)
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True).save(path)
    user32.SetWindowPos(hwnd, wintypes.HWND(-2), 0, 0, 0, 0, no_move_no_size_show)
    return True


def write_config(path, overrides, drop=None):
    merged = {section: dict(values) for section, values in BASE.items()}
    for section, keys in (drop or {}).items():
        for key in keys:
            merged[section].pop(key, None)
    for section, values in overrides.items():
        merged.setdefault(section, {}).update(values)
    lines = []
    for section, values in merged.items():
        lines.append(f"[{section}]")
        for key, value in values.items():
            lines += [f"{key}\\default=false", f"{key}={value}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def needed_sources(spec):
    """Return the SOURCES keys that a variant reads."""
    needs = set()
    if spec.get("keys"):
        needs.add("keys")
    if spec.get("firmware"):
        needs.add("firmware")
    if spec.get("save") or spec.get("nand") or spec.get("nand_from") == "real":
        needs.add("profile")
    if spec.get("nand_from") is True:
        needs.add("nand")
    return needs


def check_sources(names, sources):
    """Fail before any run if a chosen variant lacks a source folder. A late failure leaves a half-made run folder."""
    for name in names:
        for key in sorted(needed_sources(VARIANTS[name])):
            flag, env_name, meaning = SOURCES[key]
            folder = sources.get(key)
            if not folder:
                raise SystemExit(f"Variant '{name}' needs {flag} <dir> (or {env_name}): {meaning}.")
            if not folder.is_dir():
                raise SystemExit(f"Variant '{name}': {flag} is not a folder: {folder}")


def run_variant(name, spec, root, exe, seconds, game, sources):
    run = root / name
    run.mkdir(parents=True, exist_ok=False)
    binary = run / "eden-cli.exe"
    shutil.copy2(exe, binary)
    for dll in ("dxcompiler.dll", "dxil.dll", "d3dcompiler_47.dll"):
        source = exe.parent / dll
        if source.exists():
            shutil.copy2(source, run / dll)
    (run / "user" / "config").mkdir(parents=True)
    if spec.get("keys"):
        shutil.copytree(sources["keys"], run / "user" / "keys")
    if spec.get("save"):
        shutil.copytree(sources["profile"] / "nand" / "user" / "save", run / "user" / "nand" / "user" / "save")
    if spec.get("firmware"):
        shutil.copytree(sources["firmware"], run / "user" / "nand" / "system" / "Contents" / "registered")
    if spec.get("nand"):
        # A full copy keeps the save's owner profile. The real folder is never opened by the emulator.
        shutil.copytree(sources["profile"] / "nand", run / "user" / "nand")
    if spec.get("nand_from"):
        nand_source = sources["profile"] / "nand" if spec["nand_from"] == "real" else sources["nand"]
        shutil.copytree(nand_source, run / "user" / "nand")
    if spec.get("no_game_save"):
        for game_save in (run / "user" / "nand" / "user" / "save").rglob("0400C3F00006E000"):
            shutil.rmtree(game_save)
    frames = run / "frames"
    frames.mkdir()
    config = run / "probe.ini"
    write_config(config, spec.get("set", {}), spec.get("drop"))
    env = {k: v for k, v in os.environ.items() if not k.startswith("EDEN_NX2_")}
    env.update({"EDEN_NX2_FRAME_CAPTURE": str(frames),
                "EDEN_NX2_KEY_SCRIPT": os.environ.get("MATRIX_KEY_SCRIPT", KEY_SCRIPT)})
    if not spec.get("visible"):
        env["EDEN_NX2_HIDE_WINDOW"] = "1"
    # MATRIX_EXTRA_ENV="NAME=value;NAME=value" adds debug variables to one run.
    for pair in filter(None, os.environ.get("MATRIX_EXTRA_ENV", "").split(";")):
        key, _, value = pair.partition("=")
        env[key] = value
    with (run / "stdout.txt").open("wb") as out, (run / "stderr.txt").open("wb") as err:
        process = subprocess.Popen([str(binary), "-c", str(config), "-g", str(game)], cwd=run, env=env, stdout=out,
                                   stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
        (run / "process.json").write_text(json.dumps({"pid": process.pid}))
        started = time.monotonic()
        while process.poll() is None and time.monotonic() - started < seconds:
            time.sleep(0.5)
        timed_out = process.poll() is None
        if timed_out and spec.get("visible"):
            print(json.dumps({"window_grabbed": grab_window(process.pid, run / "window.png")}), flush=True)
        if timed_out:
            process.terminate()
        exit_code = process.wait(timeout=20)
    if spec.get("keys"):
        shutil.rmtree(run / "user" / "keys")
    if spec.get("firmware"):
        shutil.rmtree(run / "user" / "nand" / "system" / "Contents" / "registered")
    log = run / "user" / "log" / "eden_log.txt"
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    tga = sorted(frames.glob("*.tga"))
    result = {"variant": name, "spec": {k: (v if k == "set" else True) for k, v in spec.items()},
              "exit_code": exit_code, "timed_out": timed_out, "frames": len(tga),
              "exe_sha256": hashlib.sha256(binary.read_bytes()).hexdigest()[:16],
              "log": {p: text.count(p) for p in PATTERNS}}
    if tga:
        with Image.open(tga[-1]) as image:
            image.convert("RGB").save(run / "last.png")
    (run / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)


def montage(root, names):
    panels = []
    for name in names:
        png = root / name / "last.png"
        if png.exists():
            with Image.open(png) as image:
                panel = image.crop((0, 0, 560, 720)).resize((420, 540))
        else:
            panel = Image.new("RGB", (420, 540), (40, 40, 40))
        ImageDraw.Draw(panel).text((6, 6), name, fill=(255, 255, 0))
        panels.append(panel)
    sheet = Image.new("RGB", (420 * len(panels), 540))
    for index, panel in enumerate(panels):
        sheet.paste(panel, (420 * index, 0))
    sheet.save(root / "montage.png")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=128)
    parser.add_argument("--game", required=True)
    for key, (flag, env_name, meaning) in SOURCES.items():
        default = Path(os.environ[env_name]) if os.environ.get(env_name) else None
        parser.add_argument(flag, dest=key, type=Path, default=default,
                            help=f"{meaning}. Default: environment variable {env_name}.")
    parser.add_argument("variants", nargs="+", choices=sorted(VARIANTS))
    args = parser.parse_args()
    sources = {key: getattr(args, key) for key in SOURCES}
    if not args.exe.is_file():
        raise SystemExit(f"--exe is not a file: {args.exe}")
    check_sources(args.variants, sources)
    args.root.mkdir(parents=True, exist_ok=True)
    for name in args.variants:
        run_variant(name, VARIANTS[name], args.root, args.exe, args.seconds, args.game, sources)
    montage(args.root, args.variants)


if __name__ == "__main__":
    main()
