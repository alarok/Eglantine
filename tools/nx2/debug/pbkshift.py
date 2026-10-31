"""Compare the first changed dispatch block of a capture with the good block before it.

Usage: python pbkshift.py <capture>
Finds the word shift K with bad[i] == good[i + K], and reports rotated ring units with their flags.
"""
import sys

rows = []
for line in open(sys.argv[1], encoding="ascii").read().splitlines()[1:]:
    head, _, w = line.partition(":")
    p = head.split()
    raw = int(p[4], 16)
    rows.append((int(p[2]), int(p[3]), raw & ((1 << 40) - 1), (raw >> 42) & 0x1fffff, int(p[12]), w.split()))
ring = [r for r in rows if r[2] >> 28 == 0x210]
bad = [r for r in ring if r[4] == 1 and r[3] == 208][-1]
good = [r for r in ring if r[4] == 0 and r[3] == 208 and r[2] < bad[2]][-1]
print(f"bad  #{bad[0]} {bad[2]:#x}\ngood #{good[0]} {good[2]:#x}")
best = (0, None)
for k in range(-207, 208):
    matches = 0
    for i, w in enumerate(bad[5]):
        j = i + k
        if 0 <= j < len(good[5]) and good[5][j] == w and w != "00000000":
            matches += 1
    if matches > best[0]:
        best = (matches, k)
print(f"best shift K={best[1]} with {best[0]} nonzero matches of {sum(w != '00000000' for w in bad[5])}")
for i in range(0, 24, 8):
    print(" bad ", " ".join(bad[5][i:i + 8]))
for i in range(0, 24, 8):
    print(" good", " ".join(good[5][i:i + 8]))
print(" good tail", " ".join(good[5][-12:]))
rot = [r for r in ring if r[3] % 6 == 0 and r[5] and r[5][0] == "8000068b"]
al = [r for r in ring if r[3] % 6 == 0 and r[5] and r[5][0] == "80040e1c"]
print(f"ring units: aligned {len(al)} (changed {sum(r[4] == 1 for r in al)}), "
      f"rotated {len(rot)} (changed {sum(r[4] == 1 for r in rot)})")
if rot:
    print("first rotated:", f"#{rot[0][0]}/{rot[0][1]} {rot[0][2]:#x} changed {rot[0][4]}")
