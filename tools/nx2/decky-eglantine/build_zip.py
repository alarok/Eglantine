#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the plugin zip in a work folder, so that node_modules stays out of the repository.

Usage: python -B build_zip.py <work folder>
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PLUGIN_FOLDER = "decky-eglantine"
BUILD_INPUTS = ["package.json", "plugin.json", "pnpm-lock.yaml", "rollup.config.js", "tsconfig.json"]
ZIP_FILES = [
    "main.py",
    "plugin.json",
    "package.json",
    "README.md",
    "py_modules/eglantine_ini.py",
    "py_modules/eglantine_update.py",
]


def run(work, *args):
    # shutil.which finds the .cmd wrapper of pnpm on Windows.
    subprocess.run([shutil.which("pnpm"), *args], cwd=work, check=True, timeout=600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work")
    args = parser.parse_args()
    work = os.path.abspath(args.work)
    os.makedirs(work, exist_ok=True)

    for name in BUILD_INPUTS:
        source = os.path.join(HERE, name)
        if os.path.exists(source):
            shutil.copy2(source, work)
    shutil.copytree(os.path.join(HERE, "src"), os.path.join(work, "src"), dirs_exist_ok=True)

    run(work, "install", "--store-dir", os.path.join(work, ".pnpm-store"))
    run(work, "run", "build")

    version = json.load(open(os.path.join(HERE, "package.json"), encoding="utf-8"))["version"]
    zip_path = os.path.join(work, f"{PLUGIN_FOLDER}-v{version}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ZIP_FILES:
            archive.write(os.path.join(HERE, name), f"{PLUGIN_FOLDER}/{name}")
        archive.write(os.path.join(work, "dist", "index.js"), f"{PLUGIN_FOLDER}/dist/index.js")
        archive.write(
            os.path.join(REPO, "LICENSES", "GPL-3.0-or-later.txt"), f"{PLUGIN_FOLDER}/LICENSE"
        )

    with open(zip_path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    print(zip_path)
    print("sha256", digest)
    print("version", version)


if __name__ == "__main__":
    main()
