"""Print the frame time of each side from the "nx2 A/B" rows of a log, after a start time.

Usage: ab_means.py <log> [first second]
"""
import re
import sys

log, first = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 90.0
row = re.compile(r"^\[\s*([\d.]+)\].*nx2 A/B: A (\d+) frames (\d+) us, B (\d+) frames (\d+) us")
totals = [0, 0, 0, 0]
diffs = []
for line in open(log, encoding="utf-8", errors="replace"):
    match = row.match(line)
    if not match or float(match[1]) < first:
        continue
    a_frames, a_us, b_frames, b_us = (int(match[i]) for i in (2, 3, 4, 5))
    totals[0] += a_frames
    totals[1] += a_frames * a_us
    totals[2] += b_frames
    totals[3] += b_frames * b_us
    if a_frames > 20 and b_frames > 20:
        diffs.append(b_us - a_us)
if not totals[0] or not totals[2]:
    print("no rows")
    sys.exit(1)
a, b = totals[1] / totals[0], totals[3] / totals[2]
print(f"A {totals[0]} frames {a / 1000:.2f} ms, B {totals[2]} frames {b / 1000:.2f} ms, B-A {(b - a) / 1000:+.2f} ms")
if diffs:
    diffs.sort()
    print(f"rows {len(diffs)}, B-A by row: min {diffs[0] / 1000:+.2f} median {diffs[len(diffs) // 2] / 1000:+.2f} max {diffs[-1] / 1000:+.2f} ms")
