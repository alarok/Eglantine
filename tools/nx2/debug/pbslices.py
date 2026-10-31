"""List the entries of one memory region in a capture, with the entry before each one.

Usage: python pbslices.py <capture> <address-prefix-hex> <shift> [max]
Example: pbslices.py cap.txt 210c1 20 60 selects addresses with (addr >> 20) == 0x210c1.
"""
import sys

path, prefix, shift = sys.argv[1], int(sys.argv[2], 16), int(sys.argv[3])
limit = int(sys.argv[4]) if len(sys.argv) > 4 else 60
rows = []
for line in open(path, encoding="ascii").read().splitlines()[1:]:
    head, _, words = line.partition(":")
    p = head.split()
    raw = int(p[4], 16)
    rows.append((int(p[2]), int(p[3]), raw & ((1 << 40) - 1), (raw >> 42) & 0x1fffff, words.split(), int(p[7])))
sel = [i for i, r in enumerate(rows) if r[2] >> shift == prefix]
print(f"{len(sel)} slices")
prev_end = None
for i in sel[-limit:]:
    index, total, addr, size, words, left = rows[i]
    gap = "" if prev_end is None else f"gap {addr - prev_end}"
    prev_end = addr + size * 4
    before = rows[i - 1]
    print(f"#{index}/{total} {addr:#x} size {size:4} ({size % 6} mod 6) {gap}")
    print(f"     before: {before[2]:#x} size {before[3]} tail {' '.join(before[4][-4:])}")
    print(f"     words : {' '.join(words[:4])} .. {' '.join(words[-4:])}")
