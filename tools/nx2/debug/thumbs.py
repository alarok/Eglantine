"""Make a labelled thumbnail grid of every captured frame in a run."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

frames, output = Path(sys.argv[1]), Path(sys.argv[2])
paths = sorted(frames.glob("*.tga"))
columns, width, height = 6, 320, 180
rows = (len(paths) + columns - 1) // columns
sheet = Image.new("RGB", (columns * width, rows * height))
for index, path in enumerate(paths):
    with Image.open(path) as image:
        thumb = image.convert("RGB").resize((width, height))
    ImageDraw.Draw(thumb).text((4, 4), path.stem[-5:], fill=(255, 255, 0))
    sheet.paste(thumb, ((index % columns) * width, (index // columns) * height))
sheet.save(output)
print(output, sheet.size, len(paths))
