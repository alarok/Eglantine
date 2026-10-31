"""Show CPU use per thread of a running process, with thread names.

Usage: python threads.py <exe-name> [delay-s] [window-s] [repeats]
Waits delay-s, then measures window-s, repeats times. 100% means one full core.
"""
import ctypes
import ctypes.wintypes as w
import sys
import time

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
TH32CS_SNAPPROCESS, TH32CS_SNAPTHREAD = 0x2, 0x4
THREAD_QUERY_LIMITED_INFORMATION = 0x0800


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ProcessID", w.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", w.DWORD), ("cntThreads", w.DWORD),
                ("th32ParentProcessID", w.DWORD), ("pcPriClassBase", w.LONG), ("dwFlags", w.DWORD),
                ("szExeFile", w.WCHAR * 260)]


class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ThreadID", w.DWORD),
                ("th32OwnerProcessID", w.DWORD), ("tpBasePri", w.LONG), ("tpDeltaPri", w.LONG), ("dwFlags", w.DWORD)]


kernel32.CreateToolhelp32Snapshot.restype = w.HANDLE
kernel32.OpenThread.restype = w.HANDLE
kernel32.GetThreadDescription.argtypes = [w.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
kernel32.GetThreadTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4


def find_pid(name):
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    entry = PROCESSENTRY32W(dwSize=ctypes.sizeof(PROCESSENTRY32W))
    ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
    pid = None
    while ok:
        if entry.szExeFile.lower() == name.lower():
            pid = entry.th32ProcessID
        ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    kernel32.CloseHandle(snap)
    return pid


def sample(pid):
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    entry = THREADENTRY32(dwSize=ctypes.sizeof(THREADENTRY32))
    ok = kernel32.Thread32First(snap, ctypes.byref(entry))
    out = {}
    while ok:
        if entry.th32OwnerProcessID == pid:
            handle = kernel32.OpenThread(THREAD_QUERY_LIMITED_INFORMATION, False, entry.th32ThreadID)
            if handle:
                times = [w.FILETIME() for _ in range(4)]
                if kernel32.GetThreadTimes(handle, *[ctypes.byref(t) for t in times]):
                    total = 0
                    for t in times[2:]:
                        total += (t.dwHighDateTime << 32) | t.dwLowDateTime
                    desc = ctypes.c_wchar_p()
                    name = ""
                    if kernel32.GetThreadDescription(handle, ctypes.byref(desc)) >= 0 and desc.value:
                        name = desc.value
                    out[entry.th32ThreadID] = (total, name)
                kernel32.CloseHandle(handle)
        ok = kernel32.Thread32Next(snap, ctypes.byref(entry))
    kernel32.CloseHandle(snap)
    return out


def main():
    name = sys.argv[1]
    delay = float(sys.argv[2]) if len(sys.argv) > 2 else 0
    window = float(sys.argv[3]) if len(sys.argv) > 3 else 5
    repeats = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    time.sleep(delay)
    pid = find_pid(name)
    if pid is None:
        sys.exit(f"{name} is not running")
    for r in range(repeats):
        a = sample(pid)
        time.sleep(window)
        b = sample(pid)
        rows = []
        for tid, (total, label) in b.items():
            if tid in a:
                rows.append(((total - a[tid][0]) / 1e7 / window * 100, label or str(tid)))
        rows.sort(reverse=True)
        print(f"--- sample {r + 1}: total {sum(x[0] for x in rows):.0f}%")
        for pct, label in rows[:12]:
            print(f"  {pct:5.1f}%  {label}")


if __name__ == "__main__":
    main()
