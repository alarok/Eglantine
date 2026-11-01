"""Record the commit charge of a running emulator as a CSV, and save the largest regions.

Usage: python commitwatch.py <process.json|pid> <out.csv> [--every S] [--survey-every S] [--seconds N] [--wait S]

The first argument is the pid, or the process.json that matrix.py writes. The script waits up to
--wait seconds for that file. When it must wait, it saves the system commit at the start of the
wait in <out>.before.txt. It does not write a baseline for a pid or an existing file.

Columns (MiB):
- pagefile_usage: private commit. It does not hold the commit of a section, so it does not show
  the guest DRAM. Do not use it alone.
- shared_commit: commit of sections (Windows 11, PROCESS_MEMORY_COUNTERS_EX2). The guest DRAM is here.
- total_commit: the sum of the two. Shared commit can also be attributed to other processes.
- working_set: memory that is in RAM now.
- system_commit, commit_limit: the commit charge and the limit of the whole system.
A survey (--survey-every, 0 stops it) walks the address space and adds:
- section_committed: committed bytes of the largest section view. Check whether this is guest DRAM.
- private_committed, image_committed: committed bytes by kind.
- other_mapped_committed: committed bytes of other views. A fastmem view counts again here.
The walk can stall the target, so use --survey-every 0 in a run that measures frame time.
"""
import argparse
import csv
import ctypes
import ctypes.wintypes as w
import json
import pathlib
import time

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
PROCESS_QUERY_INFORMATION, PROCESS_VM_READ = 0x0400, 0x0010
MEM_COMMIT, MEM_RESERVE = 0x1000, 0x2000
MEM_PRIVATE, MEM_MAPPED, MEM_IMAGE = 0x20000, 0x40000, 0x1000000
MIB = 1 << 20


class PROCESS_MEMORY_COUNTERS_EX2(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD)] + [(name, ctypes.c_size_t) for name in (
        "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
        "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage",
        "PrivateWorkingSetSize", "SharedCommitUsage")]


class PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [("cb", w.DWORD)] + [(name, ctypes.c_size_t) for name in (
        "CommitTotal", "CommitLimit", "CommitPeak", "PhysicalTotal", "PhysicalAvailable", "SystemCache", "KernelTotal",
        "KernelPaged", "KernelNonpaged", "PageSize")] + [("HandleCount", w.DWORD), ("ProcessCount", w.DWORD),
                                                         ("ThreadCount", w.DWORD)]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p), ("AllocationProtect", w.DWORD),
                ("PartitionId", w.WORD), ("RegionSize", ctypes.c_size_t), ("State", w.DWORD), ("Protect", w.DWORD),
                ("Type", w.DWORD)]


kernel32.OpenProcess.restype = w.HANDLE
kernel32.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
kernel32.CloseHandle.argtypes = [w.HANDLE]
kernel32.VirtualQueryEx.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t
psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX2), w.DWORD]
psapi.GetPerformanceInfo.argtypes = [ctypes.POINTER(PERFORMANCE_INFORMATION), w.DWORD]


def process_alive(handle):
    code = w.DWORD()
    return kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value == 259


def counters(handle):
    pmc = PROCESS_MEMORY_COUNTERS_EX2(cb=ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX2))
    if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
        return None
    perf = PERFORMANCE_INFORMATION(cb=ctypes.sizeof(PERFORMANCE_INFORMATION))
    psapi.GetPerformanceInfo(ctypes.byref(perf), perf.cb)
    return dict(pagefile_usage=pmc.PagefileUsage / MIB, shared_commit=pmc.SharedCommitUsage / MIB,
                total_commit=(pmc.PagefileUsage + pmc.SharedCommitUsage) / MIB, working_set=pmc.WorkingSetSize / MIB,
                system_commit=perf.CommitTotal * perf.PageSize / MIB,
                commit_limit=perf.CommitLimit * perf.PageSize / MIB)


def regions(handle):
    address, info = 0, MEMORY_BASIC_INFORMATION()
    while kernel32.VirtualQueryEx(handle, address, ctypes.byref(info), ctypes.sizeof(info)):
        yield (info.BaseAddress or 0, info.AllocationBase or 0, info.RegionSize, info.State, info.Protect, info.Type)
        address = (info.BaseAddress or 0) + info.RegionSize


def survey(handle):
    """Sum committed bytes by kind. A section view keeps one allocation base, with committed and reserved runs."""
    views, private, image, listed = {}, 0, 0, []
    for base, allocation, size, state, protect, kind in regions(handle):
        if kind == MEM_MAPPED and state in (MEM_COMMIT, MEM_RESERVE):
            view = views.setdefault(allocation, [0, 0])
            view[0] += size
            view[1] += size if state == MEM_COMMIT else 0
        elif state == MEM_COMMIT and kind == MEM_PRIVATE:
            private += size
        elif state == MEM_COMMIT and kind == MEM_IMAGE:
            image += size
        if state == MEM_COMMIT:
            listed.append((size, kind, protect, base))
    section = max(views.values(), key=lambda view: view[0], default=(0, 0))
    mapped = sum(view[1] for view in views.values())
    listed.sort(reverse=True)
    return dict(section_span=section[0] / MIB, section_committed=section[1] / MIB, private_committed=private / MIB,
                image_committed=image / MIB, other_mapped_committed=(mapped - section[1]) / MIB), listed[:40]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("target")
    parser.add_argument("out", type=pathlib.Path)
    parser.add_argument("--every", type=float, default=5)
    parser.add_argument("--survey-every", type=float, default=30)
    parser.add_argument("--seconds", type=float, default=900)
    parser.add_argument("--wait", type=float, default=120)
    args = parser.parse_args()

    target = args.target
    if not target.isdigit():
        path, deadline = pathlib.Path(target), time.monotonic() + args.wait
        before = None
        if not path.exists():
            initial = counters(kernel32.GetCurrentProcess())
            before = initial["system_commit"] if initial else None
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        if not path.exists():
            raise SystemExit(f"process file did not appear: {path}")
        target = json.loads(path.read_text())["pid"]
        if before is not None:
            args.out.with_suffix(".before.txt").write_text(f"{before:.1f}\n")
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, int(target))
    if not handle:
        raise SystemExit(f"cannot open process {target}")

    fields = ["t", "pagefile_usage", "shared_commit", "total_commit", "working_set", "system_commit", "commit_limit",
              "section_span", "section_committed", "private_committed", "image_committed", "other_mapped_committed"]
    started, last_survey, top = time.monotonic(), -1e9, []
    with args.out.open("w", newline="") as file:
        writer = csv.DictWriter(file, fields, restval="", extrasaction="ignore")
        writer.writeheader()
        while process_alive(handle) and time.monotonic() - started < args.seconds:
            now = time.monotonic() - started
            row = counters(handle)
            if row is None:
                break
            row["t"] = now
            if args.survey_every > 0 and now - last_survey >= args.survey_every:
                extra, listed = survey(handle)
                row.update(extra)
                top = listed or top
                last_survey = now
            writer.writerow({key: f"{value:.1f}" for key, value in row.items()})
            file.flush()
            time.sleep(args.every)
    kinds = {MEM_PRIVATE: "private", MEM_MAPPED: "mapped", MEM_IMAGE: "image"}
    with args.out.with_suffix(".regions.txt").open("w") as file:
        for size, kind, protect, base in top:
            file.write(f"{size / MIB:10.1f} MiB  {kinds.get(kind, '?'):8} protect {protect:#06x}  at {base:#x}\n")
    kernel32.CloseHandle(handle)


if __name__ == "__main__":
    main()
