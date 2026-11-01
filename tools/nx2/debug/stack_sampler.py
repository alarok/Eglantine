"""Sampling profiler with call stacks for one thread of a running Windows process. No rebuild.

Usage: python stack_sampler.py <exe-name> <thread-name> <pdb-dir> [delay-s] [seconds] [hz]
It suspends the thread, walks its stack with dbghelp and resumes it. It reports:
- exclusive and inclusive time per function,
- for samples that stop in a system DLL (a wait or a syscall), which of our functions called it.
<pdb-dir> must hold a PDB with the name that the exe expects (for example eden-cli.pdb).
"""
import collections
import ctypes
import ctypes.wintypes as w
import os
import sys
import time

import rip_sampler as rs

k32 = rs.k32
k32.OpenProcess.restype = w.HANDLE
dbg = ctypes.WinDLL("dbghelp")
dbg.SymInitialize.argtypes = [w.HANDLE, ctypes.c_char_p, w.BOOL]
dbg.SymFunctionTableAccess64.argtypes = [w.HANDLE, ctypes.c_uint64]
dbg.SymFunctionTableAccess64.restype = ctypes.c_void_p
dbg.SymGetModuleBase64.argtypes = [w.HANDLE, ctypes.c_uint64]
dbg.SymGetModuleBase64.restype = ctypes.c_uint64
dbg.SymFromAddr.argtypes = [w.HANDLE, ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64),
                            ctypes.POINTER(rs.SYMBOL_INFO)]
dbg.StackWalk64.argtypes = [w.DWORD, w.HANDLE, w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
FUNC_TABLE = ctypes.WINFUNCTYPE(ctypes.c_void_p, w.HANDLE, ctypes.c_uint64)(("SymFunctionTableAccess64", dbg))
MOD_BASE = ctypes.WINFUNCTYPE(ctypes.c_uint64, w.HANDLE, ctypes.c_uint64)(("SymGetModuleBase64", dbg))
MAX_FRAMES = 24
PROCESS_ACCESS = 0x0400 | 0x0010  # query, read


def main():
    exe, thread, pdb_dir = sys.argv[1:4]
    delay = float(sys.argv[4]) if len(sys.argv) > 4 else 0
    seconds = float(sys.argv[5]) if len(sys.argv) > 5 else 10
    hz = float(sys.argv[6]) if len(sys.argv) > 6 else 150
    time.sleep(delay)
    pid = rs.find_pid(exe)
    if pid is None:
        sys.exit(f"{exe} is not running")
    tid_handle = rs.find_thread(pid, thread)
    if tid_handle is None:
        sys.exit(f"no thread named {thread}")
    process = k32.OpenProcess(PROCESS_ACCESS, False, pid)
    dbg.SymSetOptions(0x2 | 0x4)  # undecorate, deferred loads
    if not dbg.SymInitialize(process, pdb_dir.encode(), True):
        sys.exit("SymInitialize failed")
    mods = rs.modules(pid)
    main_mod = next((m for m in mods if m[2].lower() == exe.lower()), None)

    names = {}

    def name_of(address):
        if address in names:
            return names[address]
        mod = next((m for m in mods if m[0] <= address < m[0] + m[1]), None)
        if mod is None:
            result = "[JIT or unknown]"
        elif mod is not main_mod:
            result = f"[{mod[2]}]"
        else:
            sym = rs.SYMBOL_INFO(SizeOfStruct=88, MaxNameLen=1000)
            disp = ctypes.c_uint64(0)
            if dbg.SymFromAddr(process, address, ctypes.byref(disp), ctypes.byref(sym)):
                result = sym.Name.decode(errors="replace")
            else:
                result = "(no symbol)"
        names[address] = result
        return result

    name_of(main_mod[0] + 0x1000)  # loads the PDB before sampling, as it takes seconds

    raw = ctypes.create_string_buffer(1232 + 16)
    ctx = (ctypes.addressof(raw) + 15) & ~15
    frame = ctypes.create_string_buffer(512)
    stacks = []
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        if k32.SuspendThread(tid_handle) == 0xFFFFFFFF:
            continue
        ctypes.c_uint32.from_address(ctx + 0x30).value = 0x10000B  # CONTEXT_FULL for x64
        pcs = []
        if k32.GetThreadContext(tid_handle, ctx):
            ctypes.memset(frame, 0, 512)
            base = ctypes.addressof(frame)
            for offset, reg in ((0, 0xF8), (32, 0xA0), (48, 0x98)):  # PC, frame, stack
                ctypes.c_uint64.from_address(base + offset).value = \
                    ctypes.c_uint64.from_address(ctx + reg).value
                ctypes.c_uint32.from_address(base + offset + 12).value = 3  # flat mode
            for _ in range(MAX_FRAMES):
                if not dbg.StackWalk64(0x8664, process, tid_handle, base, ctx, None, FUNC_TABLE, MOD_BASE, None):
                    break
                pc = ctypes.c_uint64.from_address(base).value
                if pc == 0:
                    break
                pcs.append(pc)
        k32.ResumeThread(tid_handle)
        if pcs:
            stacks.append(pcs)
        time.sleep(1 / hz)

    exclusive, inclusive, waits = collections.Counter(), collections.Counter(), collections.Counter()
    for pcs in stacks:
        chain = [name_of(pc) for pc in pcs]
        exclusive[chain[0]] += 1
        for name in set(chain):
            inclusive[name] += 1
        if chain[0].startswith("["):
            ours = [n for n in chain if not n.startswith("[")][:4]
            waits[f"{chain[0]} <- " + " <- ".join(n[:60] for n in ours)] += 1
    total = len(stacks) or 1
    print(f"{len(stacks)} stacks of thread {thread} in {seconds:.0f} s")
    print("--- exclusive")
    for name, count in exclusive.most_common(14):
        print(f"{100 * count / total:5.1f}%  {name[:100]}")
    print("--- inclusive")
    for name, count in inclusive.most_common(34):
        print(f"{100 * count / total:5.1f}%  {name[:100]}")
    print("--- who calls the system DLLs")
    for name, count in waits.most_common(14):
        print(f"{100 * count / total:5.1f}%  {name[:230]}")
    # STACK_CALLERS=<text>: the callers of each function with that text in its name.
    wanted = os.environ.get("STACK_CALLERS")
    if wanted:
        callers = collections.Counter()
        for pcs in stacks:
            chain = [name_of(pc) for pc in pcs]
            for index, name in enumerate(chain):
                if wanted in name:
                    above = " <- ".join(n[:58] for n in chain[index + 1 : index + 4])
                    callers[f"{name[:50]} <- {above}"] += 1
                    break
        print(f"--- who calls {wanted}")
        for name, count in callers.most_common(16):
            print(f"{100 * count / total:5.1f}%  {name[:250]}")


if __name__ == "__main__":
    main()
