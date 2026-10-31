"""Print the texture cache and memory lines of a log as one table.

Usage: vram_series.py <log> [every]
"""
import re
import sys

MEMORY = re.compile(r"\[ *([\d.]+)\].*Texture cache: device memory (\d+) MiB \(expected (\d+) MiB, critical (\d+) MiB\), (\d+) ima")
HEAP = re.compile(r"VMA heap 0: usage (\d+) MiB of budget (\d+) MiB")
TURN = re.compile(r"last 600 frames: created (\d+) images, deleted (\d+) \(collector (\d+), (\d+) costly, (\d+) downloaded\)")
UPLOADS = re.compile(r"last 600 frames: (\d+) uploads from guest memory, (\d+) MiB")
FRAME = re.compile(r"last 600 presents: frame (\d+) us \(max (\d+), (\d+) over")

every = int(sys.argv[2]) if len(sys.argv) > 2 else 1
row = {}
count = 0
print("time   device expect crit images heap budget created deleted costly dl uploads MiB frame_ms max_ms over")
with open(sys.argv[1], encoding="utf-8", errors="replace") as source:
    for line in source:
        if match := FRAME.search(line):
            row["frame"] = match.groups()
        elif match := MEMORY.search(line):
            row["memory"] = match.groups()
        elif match := HEAP.search(line):
            row["heap"] = match.groups()
        elif match := TURN.search(line):
            row["turn"] = match.groups()
        elif match := UPLOADS.search(line):
            row["uploads"] = match.groups()
            count += 1
            if count % every == 0 and "memory" in row:
                time, device, expect, crit, images = row["memory"]
                heap, budget = row.get("heap", ("-", "-"))
                created, deleted, _, costly, down = row.get("turn", ("-",) * 5)
                frame, worst, over = row.get("frame", ("0", "0", "-"))
                print(f"{float(time):6.0f} {device:>6} {expect:>6} {crit:>5} {images:>6} {heap:>5} {budget:>6} "
                      f"{created:>7} {deleted:>7} {costly:>6} {down:>2} {row['uploads'][0]:>7} {row['uploads'][1]:>4} "
                      f"{int(frame) / 1000:8.1f} {int(worst) / 1000:6.0f} {over:>4}")
