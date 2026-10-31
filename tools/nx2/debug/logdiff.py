"""Compare two emulator logs (eden_log.txt) and print a table, run A against run B.

Usage: python logdiff.py <run-a-log> <run-b-log>
Shows error line counts, frame times, the EDEN_NX2_DRAW_CENSUS numbers, and the lost shader stores.
"""
import re
import sys
from collections import Counter, defaultdict

LEVELS = ("<Error>", "<Critical>", "<Warning>")
PATTERNS = ("shader rejected", "Draw skipped", "Storage buffer index", "PANIC", "Unimplemented engine", "QMD failed",
            "method out of range", "Dropping method", "Unmapped Device", "Lost shader stores")
FRAME = re.compile(r"last 600 presents: frame (\d+) us \(max (\d+), (\d+) over 100 ms\), "
                   r"blocked on the GPU fence (\d+) us \(max (\d+)\)")
SECTION = re.compile(r"Census ([^:=]+): (.*)")  # "Census window=10.0 s" has no section
PAIR = re.compile(r"(\w+)=(-?\d+)\b")
LOST = re.compile(r"Lost shader stores: (.*)")


def parse(path):
    """Read one log. The result holds the counters of every report section."""
    run = dict(lines=Counter(), frames=[], sums=Counter(), seen=Counter(), windows=0, macros=defaultdict(lambda: [0, 0]),
               images=set(), lost=set())
    with open(path, encoding="utf-8", errors="replace") as log:
        for line in log:
            for name in LEVELS + PATTERNS:
                run["lines"][name] += name in line
            found = FRAME.search(line)
            if found:
                run["frames"].append(tuple(int(n) for n in found.groups()))
            lost = LOST.search(line)
            if lost:
                run["lost"].add(lost[1].strip())
            if "Census window=" in line:
                run["windows"] += 1
            section = SECTION.search(line)
            if not section:
                continue
            name, body = section[1].strip(), section[2]
            if name == "image":
                run["images"].add(body.strip())
            elif name == "top macros":
                for group in body.split(";"):
                    pairs = dict(PAIR.findall(group))
                    if group.split():
                        total = run["macros"][group.split()[0]]
                        total[0] += int(pairs.get("zero", 0))
                        total[1] += int(pairs.get("no_draw", 0))
            else:
                run["seen"][name] += 1
                for key, value in PAIR.findall(body):
                    run["sums"][f"{name}.{key}"] += int(value)
    return run


def row(label, a, b):
    print(f"{label:<38}{a:>24}{b:>24}")


def frame_stats(run):
    frames = run["frames"]
    if not frames:
        return ["no data"] * 6
    mean = lambda column: sum(f[column] for f in frames) / len(frames)
    return [len(frames), f"{mean(0):.0f}", max(f[1] for f in frames), sum(f[2] for f in frames), f"{mean(3):.0f}",
            max(f[4] for f in frames)]


def top_macro(run):
    if not run["macros"]:
        return "none"
    token, (zero, no_draw) = max(run["macros"].items(), key=lambda item: sum(item[1]))
    return f"{token} zero={zero} no_draw={no_draw}"


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    a, b = parse(sys.argv[1]), parse(sys.argv[2])
    row("", "A", "B")
    row("--- lines", "", "")
    for name in LEVELS + PATTERNS:
        row(name, a["lines"][name], b["lines"][name])
    row("--- frame times (600-present windows)", "", "")
    labels = ("windows", "frame mean us", "frame worst us", "presents over 100 ms", "GPU fence mean us", "GPU fence worst us")
    for label, x, y in zip(labels, frame_stats(a), frame_stats(b)):
        row(label, x, y)
    row("--- census (total, mean per window)", "", "")
    row("windows", a["windows"], b["windows"])
    for key in sorted(set(a["sums"]) | set(b["sums"])):
        cells = [f"{r['sums'][key]} ({r['sums'][key] / (r['windows'] or r['seen'][key.split('.')[0]]):.1f})"
                 if key in r["sums"] else "-" for r in (a, b)]
        row(key, *cells)
    row("top macro (sums over all windows)", "", "")
    print(f"  A: {top_macro(a)}\n  B: {top_macro(b)}")
    row("distinct Census image lines", len(a["images"]), len(b["images"]))
    row("distinct Lost shader stores lines", len(a["lost"]), len(b["lost"]))
    for tag, mine, other in (("A", a, b), ("B", b, a)):
        for text in sorted(mine["lost"] - other["lost"]):
            print(f"  only in {tag}: Lost shader stores: {text[:150]}")


if __name__ == "__main__":
    main()
