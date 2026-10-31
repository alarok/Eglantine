"""Print the ring words around the entry where the unit alignment shifts.

Usage: python pbshift.py <capture> <i1,i2,...> <from-to> <address-hex>
"""
import collections
import sys

path, picks, span, target = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4], 16)
rows = []
for line in open(path, encoding="ascii").read().splitlines()[1:]:
    head, _, words = line.partition(":")
    p = head.split()
    raw = int(p[4], 16)
    rows.append((int(p[2]), int(p[3]), raw & ((1 << 40) - 1), (raw >> 42) & 0x1fffff, words.split()))
last = [i for i, r in enumerate(rows) if r[0] == 0][-1]
cur = rows[last:]
for pick in picks.split(","):
    r = [x for x in cur if x[0] == int(pick)][0]
    print(f"#{r[0]} {r[2]:#x} size {r[3]}")
    for i in range(0, len(r[4]), 6):
        print("   ", " ".join(r[4][i:i + 6]))
a, b = map(int, span.split("-"))
print(f"--- entries {a}..{b}")
for x in cur:
    if a <= x[0] <= b:
        print(f"#{x[0]} {x[2]:#x} size {x[3]} : {' '.join(x[4][:6])} .. {' '.join(x[4][-5:])}"[:170])
print(f"--- earlier visits of {target:#x}")
for r in [r for r in rows if r[2] <= target < r[2] + r[3] * 4][-3:]:
    print(f"#{r[0]}/{r[1]} {r[2]:#x} size {r[3]} : {' '.join(r[4][:8])}"[:150])
sizes = collections.Counter(r[3] for r in rows if r[2] >> 24 == target >> 24)
print("sizes in this region:", sizes.most_common(14))
