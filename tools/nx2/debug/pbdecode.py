"""Replay a pushbuffer capture (EDEN_NX2_PB_CAPTURE) offline and find where the stream breaks.

Usage: python pbdecode.py <capture> [--around N] [--last K]
The script parses the words as dma_pusher.cpp does, checks its state against the captured state
at each entry, and reports the first headers that look wrong.
"""
import argparse
import collections
import re

MODES = {1: "inc", 3: "noninc", 4: "inline", 5: "once"}


def load(path):
    entries = []
    with open(path, encoding="ascii") as f:
        reason = f.readline().strip()
        for line in f:
            head, _, words = line.partition(":")
            p = head.split()
            raw = int(p[4], 16)
            entries.append(dict(ch=int(p[1]), index=int(p[2]), total=int(p[3]), raw=raw,
                                addr=raw & ((1 << 40) - 1), size=(raw >> 42) & 0x1fffff,
                                level=(raw >> 41) & 1, sub=int(p[5]), method=int(p[6], 16), count=int(p[7]),
                                ni=p[8] == "1", io=p[9] == "1", resume=int(p[10]),
                                words=[int(w, 16) for w in words.split()]))
    return reason, entries


def parse(entry, state):
    """Parse one entry. Return the commands, as (word index, text, suspect)."""
    out = []
    for i, w in enumerate(entry["words"]):
        if state["count"]:
            state["count"] -= 1
            if not state["ni"]:
                state["method"] += 1
            if state["io"]:
                state["ni"] = True
            continue
        mode = w >> 29
        method, sub, count = w & 0x1fff, (w >> 13) & 7, (w >> 16) & 0x1fff
        suspect = None
        if mode not in MODES:
            suspect = f"mode {mode}"
        elif mode != 4 and count == 0:
            suspect = "count 0"
        elif sub not in state["bound"] and method != 0:
            suspect = f"sub {sub}"
        elif method >= 0x1000:
            suspect = f"method {method:#x}"
        out.append((i, w, MODES.get(mode, str(mode)), sub, method, count, suspect))
        if mode == 4:
            state["method"], state["sub"] = method, sub
            state["ni"], state["io"] = True, False
        elif mode in (1, 3, 5):
            state["method"], state["sub"], state["count"] = method, sub, count
            state["ni"], state["io"] = mode == 3, mode == 5
    return out


def show(e, cmds, limit=14):
    print(f"#{e['index']}/{e['total']} addr {e['addr']:#x} size {e['size']} L{e['level']} "
          f"before: sub {e['sub']} m {e['method']:#x} left {e['count']}")
    for i, w, mode, sub, method, count, suspect in cmds[:limit]:
        arg = f"val {count:#x}" if mode == "inline" else f"n {count}"
        print(f"   +{i:<4} {w:08x} {mode:6} s{sub} m{method:#05x} {arg}{'   <-- ' + suspect if suspect else ''}")
    if len(cmds) > limit:
        print(f"   ... {len(cmds) - limit} more headers")
    if e["words"]:
        print("   tail:", " ".join(f"{w:08x}" for w in e["words"][-6:]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("capture")
    ap.add_argument("--around", type=int, default=6)
    args = ap.parse_args()
    reason, entries = load(args.capture)
    print(reason)
    ch = int(re.search(r"ch (\d+)", reason)[1])
    entries = [e for e in entries if e["ch"] == ch]
    print(f"{len(entries)} entries on channel {ch}")
    state = dict(sub=0, method=0, count=0, ni=False, io=False, bound={0, 1, 2, 3, 4, 5, 6})
    parsed = []
    mismatches = suspects = 0
    first_suspect = None
    for n, e in enumerate(entries):
        if e["resume"]:
            parsed.append([])
            continue
        # The capture holds the true state: start each entry from it, as the emulator did.
        if state["count"] != e["count"] or (e["count"] and state["method"] != e["method"]):
            mismatches += 1
        state.update(sub=e["sub"], method=e["method"], count=e["count"], ni=e["ni"], io=e["io"])
        cmds = parse(e, state)
        parsed.append(cmds)
        if any(c[6] for c in cmds):
            suspects += 1
            if first_suspect is None:
                first_suspect = n
    print(f"state mismatches {mismatches}; entries with suspect headers {suspects}")
    sizes = collections.Counter(e["size"] for e in entries)
    print("common sizes:", sizes.most_common(6))
    last = len(entries) - 1
    for name, at in (("FIRST SUSPECT", first_suspect), ("END OF CAPTURE", last)):
        if at is None:
            continue
        print(f"--- {name}: entry {at}")
        for n in range(max(0, at - args.around), min(len(entries), at + 3)):
            show(entries[n], parsed[n])


if __name__ == "__main__":
    main()
