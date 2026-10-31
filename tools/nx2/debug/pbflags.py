"""Summarize the gpu_written and changed flags of a pushbuffer capture, by memory region.

Usage: python pbflags.py <capture> [last-N-to-print]
"""
import collections
import sys

path = sys.argv[1]
show = int(sys.argv[2]) if len(sys.argv) > 2 else 16
rows = []
lines = open(path, encoding="ascii").read().splitlines()
print(lines[0])
for line in lines[1:]:
    head, _, words = line.partition(":")
    p = head.split()
    raw = int(p[4], 16)
    rows.append(dict(index=int(p[2]), total=int(p[3]), addr=raw & ((1 << 40) - 1), size=(raw >> 42) & 0x1fffff,
                     left=int(p[7]), written=p[11] == "1", changed=int(p[12]), words=words.split()))
by = collections.defaultdict(collections.Counter)
for r in rows:
    region = r["addr"] >> 28
    by[region]["n"] += 1
    by[region]["written"] += r["written"]
    by[region]["changed"] += r["changed"] == 1
    by[region]["nohash"] += r["changed"] == -1
print("region        entries written changed nohash")
for region, c in sorted(by.items(), key=lambda kv: -kv[1]["n"])[:12]:
    print(f"{region:#x}0000000 {c['n']:7} {c['written']:7} {c['changed']:7} {c['nohash']:6}")
print("size of changed entries:", collections.Counter(r["size"] for r in rows if r["changed"] == 1).most_common(8))
print("last entries:")
for r in rows[-show:]:
    print(f"#{r['index']}/{r['total']} {r['addr']:#x} size {r['size']:4} left {r['left']:3} "
          f"written {int(r['written'])} changed {r['changed']:2} {' '.join(r['words'][:3])} .. {' '.join(r['words'][-3:])}")
