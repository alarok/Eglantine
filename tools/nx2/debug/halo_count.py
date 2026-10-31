"""Find frames with white halos. A halo is a large area where all three channels are near 255.

Usage: python halo_count.py <frames folder> [first] [last] [min percent]
"""
import pathlib
import re
import sys

import numpy as np
from PIL import Image

folder = pathlib.Path(sys.argv[1])
first = int(sys.argv[2]) if len(sys.argv) > 2 else 0
last = int(sys.argv[3]) if len(sys.argv) > 3 else 10**9
limit = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
checked = 0
hits = []
for path in sorted(folder.glob("nx2-frame-*")):
    number = int(re.search(r"frame-(\d+)", path.name).group(1))
    if not first <= number <= last:
        continue
    image = np.asarray(Image.open(path).convert("RGB"))
    white = (image.min(axis=2) >= 235).mean() * 100
    checked += 1
    if white >= limit:
        hits.append((number, white))
print("checked %d frames, with halos %d" % (checked, len(hits)))
for number, white in hits:
    print("  %05d white %.1f%%" % (number, white))
