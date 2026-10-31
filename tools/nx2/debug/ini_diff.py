"""Print the settings that differ between two config files.

Usage: ini_diff.py <a.ini> <b.ini>
Reads only the emulation sections. Skips paths, names, tokens and keys.
"""
import re
import sys

SECTIONS = {"Renderer", "Cpu", "Core", "System", "Audio", "Debugging", "Miscellaneous", "GpuDriver"}
SKIP = re.compile(r"token|username|password|key|path|dir|device_name|rng_seed|custom_rtc", re.I)


def load(name):
    values, section = {}, ""
    with open(name, encoding="utf-8", errors="replace") as source:
        for raw in source:
            line = raw.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
            elif "=" in line and section in SECTIONS:
                key, value = line.split("=", 1)
                if not SKIP.search(key):
                    values[f"{section}/{key}"] = value
    return values


def effective(values):
    """Returns the value of each key. A key with default=true uses the program's default."""
    result = {}
    for key, value in values.items():
        if key.endswith("\\default"):
            continue
        result[key] = "(default)" if values.get(key + "\\default") == "true" else value
    return result


a, b = effective(load(sys.argv[1])), effective(load(sys.argv[2]))
print(f"{'setting':<52} {'A':<14} B")
for key in sorted(set(a) | set(b)):
    if a.get(key) != b.get(key):
        print(f"{key:<52} {str(a.get(key, '-')):<14} {b.get(key, '-')}")
