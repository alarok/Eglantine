"""Find entries in a capture whose words equal what the same addresses held in an earlier entry.

Usage: python pbstale.py <capture> [last-N-to-print]
A ring revisits its addresses. A slice that holds the same words as on the previous visit was
either rewritten with equal data or never rewritten (stale).
"""
import collections
import sys

path = sys.argv[1]
show = int(sys.argv[2]) if len(sys.argv) > 2 else 30
rows = []
for line in open(path, encoding="ascii").read().splitlines()[1:]:
    head, _, words = line.partition(":")
    p = head.split()
    raw = int(p[4], 16)
    rows.append((int(p[1]), int(p[2]), int(p[3]), raw & ((1 << 40) - 1), (raw >> 42) & 0x1fffff, words.split()))
seen = {}
report = []
revisit = 0
for n, (ch, index, total, addr, size, words) in enumerate(rows):
    same = known = 0
    last_n = None
    for i, w in enumerate(words):
        a = addr + i * 4
        if a in seen:
            known += 1
            if seen[a][0] == w:
                same += 1
            last_n = seen[a][1]
    if known:
        revisit += 1
        report.append((n, index, total, addr, size, known, same, last_n, " ".join(words[:3])))
    for i, w in enumerate(words):
        seen[addr + i * 4] = (w, n)
print(f"{len(rows)} entries, {revisit} revisit known addresses")
regions = collections.Counter()
same_regions = collections.Counter()
for r in report:
    regions[r[3] >> 28] += 1
    if r[6] == r[5] and r[5] == r[4]:
        same_regions[r[3] >> 28] += 1
for region, count in regions.most_common(10):
    print(f"  region {region:#x}0000000: {count} revisits, {same_regions[region]} with all words equal")
print("last revisits (entry, addr, size, known, same, age in entries, first words):")
for n, index, total, addr, size, known, same, last_n, first in report[-show:]:
    print(f"  #{index}/{total} {addr:#x} size {size} known {known} same {same} age {n - last_n} {first}")
