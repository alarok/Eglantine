---
name: nx2-debug-tools
description: Debug a Switch 2 game fault in Eglantine from logs instead of by eye. Use when a game shows invisible or black geometry, missing textures, a frozen stream or a GPU fault with no error line, or to compare two builds or settings. Covers the draw census, lost shader stores, the command stream capture and the tools in tools/nx2/debug.
---

# NX2 debug tools

Find a silent fault from a log in minutes. Each failure this skill covers shows no error line.
`tools/nx2/debug/README.md` has the usage of each tool and how to read each census number.

## Steps

1. **Check for a free machine.** Only one heavy emulator runs at a time. `play.ps1` prints `BUSY` and exits with 1 if a game runs. Stop only your own processes, by PID. Do not start a second game.
2. **Build at low priority.** The owner can play at the same time. Run it from PowerShell, not Git Bash:
   ```powershell
   cmd /c 'start "" /belownormal /wait /b cmd /c "D:\DEV\egl-build-cli.cmd <worktree>"'
   ```
3. **Make the local games file once.** Copy nothing from a real profile. Write `tools/nx2/debug/games.local.json` with `{"bananza": "<exefs main>"}`. Git ignores it.
4. **Run a good case and a bad case.** Change one thing between them.
   ```powershell
   $env:MATRIX_NAND_FROM = '<seed nand folder>'   # Only for seed-play variants
   $env:MATRIX_EXTRA_ENV = 'EDEN_NX2_DRAW_CENSUS=1;EDEN_NX2_RESETFIX=0'
   powershell -NoProfile -File tools/nx2/debug/play.ps1 <eden-cli.exe> <label> bananza 150 seed-play -OutDir <dir on D:>
   ```
5. **Compare the logs.** `python -B tools/nx2/debug/logdiff.py <good log> <bad log>`. The log is `<dir>/<label>-<game>/<variant>/user/log/eden_log.txt`.
6. **Look at the frames.** `<dir>/<label>-<game>/thumbs.png`. A count does not prove a visual fault. Look before you claim one.
7. **If the stream breaks,** add `EDEN_NX2_PB_CAPTURE=<file>`, and read the file with `pbdecode.py` first, then `pbflags.py` and `pbstale.py`.

## What each signal found

- Macro with `no_draw` high and `macro_indirect` at 0: the draw records have 0 copies. Look for the program that writes them.
- `Lost shader stores`: that program writes through a loaded pointer. See `044944dd9a`.
- `Census image:` lines and `draws_sampling`: the images have no memory. Explain the missing texture from these first.
- A capture with `changed=1` on pages with `gpu_written=0`: the guest rewrote command memory before the GPU thread read it.

## Traps

- `matrix.py` removes each `EDEN_NX2_*` variable from the child. Use `MATRIX_EXTRA_ENV`. A variable set in the parent shell does not reach the game.
- The split GPU thread does not start at `gpu_accuracy=1`, which is the default of `matrix.py`. Use `seed-play-acc0` to run with it. The macro tags take another path there, so test both.
- A 10 s window hides a short event. Use `EDEN_NX2_DRAW_CENSUS_SECONDS=2`.
- `Enabled()` values read at program start cannot see `nx2_switches.txt`, because `main()` reads that file later. Read a new switch at first use.
- A successful `Track` does not prove a mapped store: it follows a loaded pointer to the constant buffer that holds the list. Count the store as lost with `ReachesCbufWithoutLoad`, not with the result of `Track`.
- Edit no source file while Ninja builds: an object can finish after the edit and stay stale. Touch the file after the build if you did.
- Keep test files and run folders on D:. Use isolated profiles. Never copy a real `qt-config.ini`.
