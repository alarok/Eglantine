"""Name module offsets of an exe with its PDB through dbghelp. No cdb needed.

Usage: python symbolize.py <exe> <pdb-dir> <offset> [<offset> ...]
Offsets are RVAs, as in the Windows crash event or in eden-cli+0x... stacks.
"""
import ctypes
import ctypes.wintypes as w
import sys


class SYMBOL_INFO(ctypes.Structure):
    _fields_ = [
        ("SizeOfStruct", w.ULONG), ("TypeIndex", w.ULONG), ("Reserved", ctypes.c_uint64 * 2),
        ("Index", w.ULONG), ("Size", w.ULONG), ("ModBase", ctypes.c_uint64),
        ("Flags", w.ULONG), ("Value", ctypes.c_uint64), ("Address", ctypes.c_uint64),
        ("Register", w.ULONG), ("Scope", w.ULONG), ("Tag", w.ULONG),
        ("NameLen", w.ULONG), ("MaxNameLen", w.ULONG), ("Name", ctypes.c_char * 2000),
    ]


class LINE64(ctypes.Structure):
    _fields_ = [
        ("SizeOfStruct", w.DWORD), ("Key", ctypes.c_void_p), ("LineNumber", w.DWORD),
        ("FileName", ctypes.c_char_p), ("Address", ctypes.c_uint64),
    ]


def main():
    exe, pdb_dir, offsets = sys.argv[1], sys.argv[2], sys.argv[3:]
    dbg = ctypes.WinDLL("dbghelp")
    dbg.SymLoadModuleEx.restype = ctypes.c_uint64
    dbg.SymLoadModuleEx.argtypes = [w.HANDLE, w.HANDLE, ctypes.c_char_p, ctypes.c_char_p,
                                    ctypes.c_uint64, w.DWORD, ctypes.c_void_p, w.DWORD]
    dbg.SymFromAddr.argtypes = [w.HANDLE, ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64),
                                ctypes.POINTER(SYMBOL_INFO)]
    dbg.SymGetLineFromAddr64.argtypes = [w.HANDLE, ctypes.c_uint64, ctypes.POINTER(w.DWORD),
                                         ctypes.POINTER(LINE64)]
    proc = w.HANDLE(0x1234)
    SYMOPT_LOAD_LINES, SYMOPT_UNDNAME = 0x10, 0x2
    dbg.SymSetOptions(SYMOPT_LOAD_LINES | SYMOPT_UNDNAME)
    if not dbg.SymInitialize(proc, pdb_dir.encode(), False):
        sys.exit("SymInitialize failed")
    base = 0x140000000
    if not dbg.SymLoadModuleEx(proc, None, exe.encode(), None, base, 0, None, 0):
        sys.exit("SymLoadModuleEx failed")
    for text in offsets:
        addr = base + int(text, 16)
        sym = SYMBOL_INFO(SizeOfStruct=ctypes.sizeof(SYMBOL_INFO) - 2000 + 1, MaxNameLen=2000)
        disp = ctypes.c_uint64(0)
        name = "?"
        if dbg.SymFromAddr(proc, addr, ctypes.byref(disp), ctypes.byref(sym)):
            name = f"{sym.Name.decode(errors='replace')}+0x{disp.value:x}"
        line = LINE64(SizeOfStruct=ctypes.sizeof(LINE64))
        ldisp = w.DWORD(0)
        where = ""
        if dbg.SymGetLineFromAddr64(proc, addr, ctypes.byref(ldisp), ctypes.byref(line)):
            where = f"  {line.FileName.decode(errors='replace')}:{line.LineNumber}"
        print(f"{text}: {name}{where}")


if __name__ == "__main__":
    main()
