"""Print the mean brightness of each captured frame, to find black views.

Usage: frame_luma.py <frames folder> [every]
The mean uses the middle of the frame, so the HUD does not hide a black view.
"""
import pathlib
import sys

from PIL import Image

every = int(sys.argv[2]) if len(sys.argv) > 2 else 1
for index, path in enumerate(sorted(pathlib.Path(sys.argv[1]).glob("*.tga"))):
    if index % every:
        continue
    image = Image.open(path).convert("L")
    width, height = image.size
    middle = image.crop((width // 6, height // 6, width * 5 // 6, height * 5 // 6))
    values = sorted(middle.resize((64, 36), Image.BOX).tobytes())
    mean = sum(values) / len(values)
    print(f"{path.stem[-5:]} mean {mean:6.1f} median {values[len(values) // 2]:4d} bright10 {values[len(values) * 9 // 10]:4d}")
