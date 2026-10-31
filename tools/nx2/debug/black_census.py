"""Count black 3D views in each run, and print the settings of the run.

Usage: black_census.py <root folder>
A frame counts when the middle is black and the HUD corner is lit, after the first lit middle frame
that follows the title screen. The probe.ini of the run gives the settings.
"""
import pathlib
import re
import sys

from PIL import Image

SETTINGS = ("gpu_accuracy", "accelerate_astc", "use_asynchronous_shaders", "barrier_feedback_loops", "astc_recompression")


def brightness(image, box):
    return sum(image.crop(box).resize((32, 18), Image.BOX).tobytes()) / (32 * 18)


def settings_of(config):
    found = {}
    if config.exists():
        with open(config, encoding="utf-8", errors="replace") as source:
            for line in source:
                name, _, value = line.strip().partition("=")
                if name in SETTINGS:
                    found[name] = value
    return found


root = pathlib.Path(sys.argv[1])
for frames in sorted(root.glob("**/frames")):
    paths = sorted(frames.glob("*.tga"))
    if len(paths) < 40:
        continue
    run = frames.parent
    black = []
    for path in paths:
        try:
            image = Image.open(path).convert("L")
        except OSError:
            continue
        width, height = image.size
        middle = brightness(image, (width // 6, height // 6, width * 5 // 6, height * 5 // 6))
        hud = brightness(image, (width * 3 // 100, height * 4 // 100, width * 20 // 100, height * 22 // 100))
        if middle < 1 and hud > 8:
            black.append(path.stem[-5:])
    values = settings_of(run / "probe.ini")
    short = " ".join(f"{k[:5]}={v}" for k, v in values.items())
    span = f"{black[0]}..{black[-1]}" if black else "-"
    print(f"{run.parent.name}/{run.name:<20} frames {len(paths):4d} black {len(black):3d} {span:<14} {short}", flush=True)
