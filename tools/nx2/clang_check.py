#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compile changed code with Clang before a push, without an object file.

MSVC accepts code that the release jobs refuse: narrowing in braces and a discarded [[nodiscard]]
value. Each such fault cost a release run of 30 minutes. This tool finds them in seconds on a local
MSVC build folder. It reads compile_commands.json and runs clang-cl -fsyntax-only with the warning
flags of the Linux and MinGW jobs.

It selects the translation units that use a file changed since --base. It finds these units in the
Ninja dependency log. Use --all to check each unit under src/.

Limit: it reads the Windows branches of the code with the MSVC standard library. Code in a Linux
#ifdef and faults that only libstdc++ shows stay hidden. The compile-check workflow covers these.

Usage: clang_check.py <build dir> [--base origin/nx2] [--all] [--only text] [-j 4]
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CLANG_CL = r"C:\Program Files\LLVM\bin\clang-cl.exe"

# The flags of src/CMakeLists.txt for GCC and Clang.
CI_FLAGS = """
-fsyntax-only -ferror-limit=0 /W3
/clang:-Werror=all /clang:-Werror=extra /clang:-Werror=missing-declarations
/clang:-Werror=shadow /clang:-Werror=unused
/clang:-Wno-attributes /clang:-Wno-invalid-offsetof /clang:-Wno-unused-parameter
/clang:-Wno-missing-field-initializers /clang:-Wno-braced-scalar-init
/clang:-Wno-unused-private-field /clang:-Wno-nullability-completeness
/clang:-Wno-unused-command-line-argument /clang:-Wno-unknown-pragmas
/clang:-Wno-ignored-pragma-optimize
"""

# Options that only have a use for a real compile. /Fo and /Fd take their value in the same word.
DROP = re.compile(r'(?:^|\s)(?:/Fo|/Fd|/FS|/showIncludes|/Zi|/Z7|/MP|/GL|/Yu|/Yc|/Fp)\S*')
ERROR = re.compile(r'^(.+?)\((\d+),(\d+)\): (?:fatal )?error: (.*)$')


def changed_files(source, base):
    out = subprocess.run(['git', '-C', str(source), 'diff', '--name-only', base], check=True,
                         capture_output=True, text=True, timeout=60).stdout
    return {str((source / line).resolve()).lower() for line in out.splitlines() if line.strip()}


def users_of(build, ninja, files):
    """Returns the object files that the dependency log links to one of the files."""
    out = subprocess.run([ninja, '-C', str(build), '-t', 'deps'], check=True, capture_output=True,
                         text=True, errors='replace', timeout=120).stdout
    # The log has millions of lines but few different headers, and each resolve reads the disk.
    known = {}
    objects, current = set(), None
    for line in out.splitlines():
        if line and not line[0].isspace():
            current = line.split(':')[0].strip().replace('\\', '/').lower()
        elif name := line.strip():
            if name not in known:
                known[name] = str(Path(name).resolve()).lower() in files
            if known[name]:
                objects.add(current)
    return objects


def check(entry, source, flags_file):
    raw = entry['command']
    args = raw[raw.lower().index('cl.exe') + len('cl.exe'):].lstrip('" ')
    args = DROP.sub(' ', args)
    # The third party headers are not ours to fix.
    args = re.sub(r'-I(\S*[\\/]\.cache[\\/]cpm[\\/]\S*)', r'/imsvc \1', args)
    # src/yuzu_cmd/CMakeLists.txt allows this for GCC and Clang.
    if 'yuzu_cmd' in Path(entry['file']).parts:
        args = '/clang:-Wno-unused-variable ' + args
    with tempfile.TemporaryDirectory(dir=Path(flags_file).parent) as folder:
        rsp = Path(folder) / 'args.rsp'
        rsp.write_text(args, encoding='utf-8')
        result = subprocess.run([CLANG_CL, f'@{flags_file}', f'@{rsp}'], capture_output=True,
                                text=True, errors='replace', cwd=entry['directory'], timeout=600,
                                creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    errors = set()
    root = str(source / 'src').lower().replace('/', '\\')
    for line in (result.stdout + result.stderr).splitlines():
        match = ERROR.match(line)
        if match and str(Path(match[1]).resolve()).lower().startswith(root):
            errors.add(f'{Path(match[1]).resolve()}:{match[2]}: {match[4]}')
    return entry['file'], errors


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('build', type=Path)
    parser.add_argument('--base', default='origin/nx2')
    parser.add_argument('--all', action='store_true', help='check each unit under src/')
    parser.add_argument('--only', action='append', default=[],
                        help='check only units with this text in the path. Use it more than once '
                             'to give more texts')
    parser.add_argument('-j', type=int, default=4)
    args = parser.parse_args()

    source = ninja = None
    for line in (args.build / 'CMakeCache.txt').read_text(errors='replace').splitlines():
        if line.startswith('CMAKE_HOME_DIRECTORY:'):
            source = Path(line.split('=', 1)[1])
        elif line.startswith('CMAKE_MAKE_PROGRAM:'):
            ninja = line.split('=', 1)[1]
    entries = json.loads((args.build / 'compile_commands.json').read_text(errors='replace'))
    entries = [e for e in entries if e['file'].endswith('.cpp')
               and Path(e['file']).is_relative_to(source / 'src')
               and (not args.only
                    or any(text in e['file'].replace('\\', '/') for text in args.only))]
    if not args.all:
        files = changed_files(source, args.base)
        users = users_of(args.build, ninja, files)
        entries = [e for e in entries
                   if str(Path(e['file']).resolve()).lower() in files
                   or str(Path(e['output']).relative_to(args.build)).replace('\\', '/').lower() in users]

    start = time.time()
    all_errors = set()
    with tempfile.TemporaryDirectory() as folder:
        flags_file = Path(folder) / 'flags.rsp'
        flags_file.write_text(CI_FLAGS, encoding='utf-8')
        with ThreadPoolExecutor(args.j) as pool:
            for name, errors in pool.map(lambda e: check(e, source, flags_file), entries):
                all_errors |= errors
    for line in sorted(all_errors):
        print(line)
    print(f'{len(entries)} units, {len(all_errors)} errors, {time.time() - start:.0f} s')
    return 1 if all_errors else 0


if __name__ == '__main__':
    sys.exit(main())
