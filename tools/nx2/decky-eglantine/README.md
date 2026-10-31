# Eglantine settings for Decky

This Decky Loader plugin shows a small set of Eglantine settings in the Steam Quick Access menu on SteamOS.
Game Mode has no easy way to open the emulator's settings.

## What it changes

Each control writes the current game file or the global file:

| Control | Key | File section |
|---|---|---|
| Resolución | `resolution_setup` | `Renderer` |
| Filtro | `scaling_filter` | `Renderer` |
| Modo GPU | `gpu_accuracy` | `Renderer` |
| Consola | `use_docked_mode` | `System` |
| Generar fotogramas | `frame_gen`, `frame_gen_multiplier`, `frame_gen_type` | `Renderer` |
| DMA (shown when it is not Default) | `dma_accuracy` | `Renderer` |

Files:

- Global: `~/.config/eden/qt-config.ini`.
- Game: `~/.config/eden/custom/<title>.ini`. The emulator makes this file at the first boot of the game.

A value applies at the next game start. The emulator has no reload path yet.

## Rules for the files

- The plugin reads the emulator's file format as in `src/frontend_common/config.cpp`.
- A write replaces only the lines of that key. All other bytes stay.
- The first write to a file makes a copy, `<file>.decky-bak`. The plugin does not change this copy after that.
- A write goes to a temporary file, then replaces the file in one step.
- A value is always written with `key\default=false`. The plugin does not compare with a built-in default, because the defaults change between builds.
- The first option of each control removes the value. In the global scope, it sets `key\default=true`. In a game scope, it sets `key\use_global=true`.

## Writes while the emulator runs

The emulator saves the global file from memory at each boot and at a clean exit, so a change made during play can be lost. The panel locks the global controls while an `eglantine` process runs.

The emulator writes a game file only at the boot of that game and in the per-game dialog. The panel keeps the game controls open during play. Do not open the per-game dialog at the same time.

## Current game

The panel takes the title from the last `Loading <name> (<title>) ...` line in `~/.local/share/eden/log/eden_log.txt`. The name of a loose dump is `Unknown program`, so a short table in `eglantine_ini.py` gives the known names.

## Build

Node.js and pnpm are necessary. Give a work folder outside the repository:

```bash
python -B build_zip.py E:/DEV/decky-eglantine-build
```

The output is `decky-eglantine-v<version>.zip`, with its SHA-256.

## Test

```bash
python -B -m unittest discover -s tests
```

## Install

Decky Settings, Developer, "Install plugin from ZIP" takes the zip when developer mode is on. The loader also takes a `file://` path in its install route.

To remove the plugin, use Decky Settings, Plugins. This does not remove the changed values or the `.decky-bak` files.
