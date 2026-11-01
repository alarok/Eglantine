"""Sampling profiler for one thread of a running Windows process. It needs no rebuild.

Usage: python rip_sampler.py <exe-name> <thread-name> <symbol-exe> <pdb-dir> [delay-s] [seconds] [hz]
It suspends the thread many times per second, reads its instruction pointer, and resumes it.
It prints the functions and modules where the thread spends its time, and it sorts the samples into
blocking wait, spin and the rest.

Every module gets symbols. System modules (ntdll, win32u) need a PDB from the public Microsoft
symbol server: the dbghelp of Windows has no symsrv.dll beside it, so this script loads the copy in
the Debugging Tools folder. Set DBGHELP_DIR to that folder, and SYM_CACHE to the download cache.
It prints samples per symbol: it does not unwind. To see which of our functions called a wait, use
stack_sampler.py, which walks the stack with the thread suspended.
<pdb-dir> must hold the PDB of the exe, with the name that the exe expects (eden-cli.pdb).
"""
import collections
import ctypes
import ctypes.wintypes as w
import os
import sys
import time

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
TH_PROCESS, TH_THREAD, TH_MODULE, TH_MODULE32 = 0x2, 0x4, 0x8, 0x10
THREAD_ACCESS = 0x0002 | 0x0008 | 0x0040 | 0x0800  # suspend, get context, query, limited query
k32.CreateToolhelp32Snapshot.restype = w.HANDLE
k32.OpenThread.restype = w.HANDLE
k32.GetThreadDescription.argtypes = [w.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
k32.SuspendThread.argtypes = [w.HANDLE]
k32.ResumeThread.argtypes = [w.HANDLE]
k32.GetThreadContext.argtypes = [w.HANDLE, ctypes.c_void_p]
k32.CloseHandle.argtypes = [w.HANDLE]
k32.OpenProcess.restype = w.HANDLE
k32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k32.ReadProcessMemory.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t)]
PROCESS_VM_READ = 0x0010

# Symbol names that mean "this thread gave the CPU away" rather than "this thread worked".
WAITS = (
    "NtWaitForSingleObject", "NtWaitForMultipleObjects", "NtDelayExecution",
    "NtWaitForAlertByThreadId", "NtWaitForWorkViaWorkerFactory", "NtYieldExecution",
    "NtRemoveIoCompletion", "NtWaitForKeyedEvent",
    "WaitForSingleObject", "Sleep", "SwitchToThread", "RtlpWaitOnAddress", "RtlpWaitForCriticalSection",
    "RtlpWaitOnCriticalSection",
)

# This thread waits for the other GPU thread here, but it keeps the CPU: a spin is not work.
SPINS = ("GpuSplit::Drain", "GpuSplit::BackLoop", "::Pause")


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ProcessID", w.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", w.DWORD), ("cntThreads", w.DWORD),
                ("th32ParentProcessID", w.DWORD), ("pcPriClassBase", w.LONG), ("dwFlags", w.DWORD),
                ("szExeFile", w.WCHAR * 260)]


class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ThreadID", w.DWORD),
                ("th32OwnerProcessID", w.DWORD), ("tpBasePri", w.LONG), ("tpDeltaPri", w.LONG), ("dwFlags", w.DWORD)]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("th32ModuleID", w.DWORD), ("th32ProcessID", w.DWORD),
                ("GlblcntUsage", w.DWORD), ("ProccntUsage", w.DWORD), ("modBaseAddr", ctypes.c_void_p),
                ("modBaseSize", w.DWORD), ("hModule", w.HMODULE), ("szModule", w.WCHAR * 256),
                ("szExePath", w.WCHAR * 260)]


class SYMBOL_INFO(ctypes.Structure):
    _fields_ = [("SizeOfStruct", w.ULONG), ("TypeIndex", w.ULONG), ("Reserved", ctypes.c_uint64 * 2),
                ("Index", w.ULONG), ("Size", w.ULONG), ("ModBase", ctypes.c_uint64), ("Flags", w.ULONG),
                ("Value", ctypes.c_uint64), ("Address", ctypes.c_uint64), ("Register", w.ULONG),
                ("Scope", w.ULONG), ("Tag", w.ULONG), ("NameLen", w.ULONG), ("MaxNameLen", w.ULONG),
                ("Name", ctypes.c_char * 1000)]


def find_pid(name):
    snap = k32.CreateToolhelp32Snapshot(TH_PROCESS, 0)
    e = PROCESSENTRY32W(dwSize=ctypes.sizeof(PROCESSENTRY32W))
    ok, pid = k32.Process32FirstW(snap, ctypes.byref(e)), None
    while ok:
        if e.szExeFile.lower() == name.lower():
            pid = e.th32ProcessID
        ok = k32.Process32NextW(snap, ctypes.byref(e))
    k32.CloseHandle(snap)
    return pid


def find_thread(pid, wanted):
    snap = k32.CreateToolhelp32Snapshot(TH_THREAD, 0)
    e = THREADENTRY32(dwSize=ctypes.sizeof(THREADENTRY32))
    ok, found = k32.Thread32First(snap, ctypes.byref(e)), None
    while ok:
        if e.th32OwnerProcessID == pid:
            h = k32.OpenThread(THREAD_ACCESS, False, e.th32ThreadID)
            if h:
                d = ctypes.c_wchar_p()
                if k32.GetThreadDescription(h, ctypes.byref(d)) >= 0 and d.value == wanted:
                    found = h
                else:
                    k32.CloseHandle(h)
        ok = k32.Thread32Next(snap, ctypes.byref(e))
    k32.CloseHandle(snap)
    return found


def modules(pid):
    """Return (base, size, name, path) of every module of the process."""
    snap = k32.CreateToolhelp32Snapshot(TH_MODULE | TH_MODULE32, pid)
    e = MODULEENTRY32W(dwSize=ctypes.sizeof(MODULEENTRY32W))
    ok, out = k32.Module32FirstW(snap, ctypes.byref(e)), []
    while ok:
        out.append((e.modBaseAddr or 0, e.modBaseSize, e.szModule, e.szExePath))
        ok = k32.Module32NextW(snap, ctypes.byref(e))
    k32.CloseHandle(snap)
    return sorted(out)


def main():
    exe, thread, sym_exe, pdb_dir = sys.argv[1:5]
    delay = float(sys.argv[5]) if len(sys.argv) > 5 else 0
    seconds = float(sys.argv[6]) if len(sys.argv) > 6 else 10
    hz = float(sys.argv[7]) if len(sys.argv) > 7 else 500
    time.sleep(delay)
    pid = find_pid(exe)
    if pid is None:
        sys.exit(f"{exe} is not running")
    handle = find_thread(pid, thread)
    if handle is None:
        sys.exit(f"no thread named {thread}")
    mods = modules(pid)
    raw = ctypes.create_string_buffer(1232 + 16)
    ctx = (ctypes.addressof(raw) + 15) & ~15
    ctypes.c_uint32.from_address(ctx + 0x30).value = 0x100001  # CONTEXT_CONTROL for x64
    samples = []
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        if k32.SuspendThread(handle) != 0xFFFFFFFF:
            if k32.GetThreadContext(handle, ctx):
                samples.append((ctypes.c_uint64.from_address(ctx + 0xF8).value,
                                ctypes.c_uint64.from_address(ctx + 0x98).value))
            k32.ResumeThread(handle)
        time.sleep(1 / hz)

    # The dbghelp of Windows has no symsrv.dll beside it, so it cannot download a PDB.
    # The copy in the Debugging Tools folder can, and it reads the same files.
    dbg = None
    env_dir = os.environ.get("DBGHELP_DIR", "")
    for folder in ([env_dir] if env_dir else []) + [r"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64",
                                                   r"C:\Program Files\Windows Kits\10\Debuggers\x64"]:
        path = os.path.join(folder, "dbghelp.dll")
        if os.path.isfile(path) and os.path.isfile(os.path.join(folder, "symsrv.dll")):
            try:
                dbg = ctypes.WinDLL(path)
                break
            except OSError:
                pass
    if dbg is None:
        dbg = ctypes.WinDLL("dbghelp")
    dbg.SymLoadModuleEx.restype = ctypes.c_uint64
    dbg.SymLoadModuleEx.argtypes = [w.HANDLE, w.HANDLE, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint64,
                                    w.DWORD, ctypes.c_void_p, w.DWORD]
    dbg.SymFromAddr.argtypes = [w.HANDLE, ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64),
                                ctypes.POINTER(SYMBOL_INFO)]
    proc = w.HANDLE(0x1234)
    dbg.SymSetOptions(0x2)
    cache = os.environ.get("SYM_CACHE", r"D:\DEV\tmp\sym")
    os.makedirs(cache, exist_ok=True)
    search = f"srv*{cache}*https://msdl.microsoft.com/download/symbols;{pdb_dir}"
    dbg.SymInitialize(proc, search.encode(), False)
    fixed = 0x140000000  # base that the link map of the exe in the PDB expects
    loaded = set()
    for base, size, name, path in mods:
        if name.lower() == os.path.basename(sym_exe).lower():
            base = fixed
            size = 0
        if dbg.SymLoadModuleEx(proc, None, (path or name).encode(), None, base, size, None, 0):
            loaded.add(name.lower())

    by_module, by_func = collections.Counter(), collections.Counter()
    by_wait = collections.Counter()
    by_spin = collections.Counter()
    resolved = {}
    main_mod = next((m for m in mods if m[2].lower() == exe.lower()), None)
    for rip, rsp in samples:
        mod = next((m for m in mods if m[0] <= rip < m[0] + m[1]), None)
        by_module[mod[2] if mod else "(JIT or unknown)"] += 1
        if not mod:
            by_func["[JIT or unknown]"] += 1
            continue
        key = (mod[2].lower(), rip - mod[0])
        sym_name = resolved.get(key)
        if sym_name is None:
            sym_name = ""
            if mod[2].lower() in loaded:
                sym = SYMBOL_INFO(SizeOfStruct=88, MaxNameLen=1000)
                disp = ctypes.c_uint64(0)
                addr = rip if mod is not main_mod else rip - mod[0] + fixed
                if dbg.SymFromAddr(proc, addr, ctypes.byref(disp), ctypes.byref(sym)):
                    sym_name = sym.Name.decode(errors="replace")
            resolved[key] = sym_name
        label = sym_name if mod is main_mod or not sym_name else f"{mod[2]}!{sym_name}"
        by_func[label or f"[{mod[2]}]"] += 1
        bare = sym_name.split("::")[-1].lstrip("_")
        # Nt and Zw names can refer to the same system call.
        wait_name = "Nt" + bare[2:] if bare.startswith("Zw") else bare
        if any(wait_name.startswith(waiter) for waiter in WAITS):
            by_wait[bare] += 1
        elif any(spin in sym_name for spin in SPINS):
            by_spin[bare] += 1

    total = len(samples) or 1
    print(f"{len(samples)} samples of thread {thread} in {seconds:.0f} s")
    print(f"symbols loaded: {len(loaded)} of {len(mods)} modules")
    print("--- modules")
    for name, count in by_module.most_common(12):
        print(f"{100 * count / total:5.1f}%  {name}")
    print("--- waits (thread gave the CPU away)")
    wait_total = sum(by_wait.values())
    for name, count in by_wait.most_common(10):
        print(f"{100 * count / total:5.1f}%  {name[:110]}")
    print("--- spins (keeps the CPU while it waits for the other GPU thread)")
    spin_total = sum(by_spin.values())
    for name, count in by_spin.most_common(6):
        print(f"{100 * count / total:5.1f}%  {name[:110]}")
    print(f"{100 * wait_total / total:5.1f}%  BLOCKING WAIT")
    print(f"{100 * spin_total / total:5.1f}%  SPIN (an upper bound: the frame of a loop is not all a spin)")
    print(f"{100 * (total - wait_total - spin_total) / total:5.1f}%  OTHER (work, or a wait that no symbol shows)")
    print("--- functions")
    for name, count in by_func.most_common(40):
        print(f"{100 * count / total:5.1f}%  {name[:110]}")


if __name__ == "__main__":
    main()
