---
name: nx2-debug-tools
description: Debug a Switch 2 game fault in Eglantine from logs instead of by eye. Use when a game shows invisible or black geometry, missing textures, a frozen stream or a GPU fault with no error line, or to compare two builds or settings. Covers the draw census, lost shader stores, the command stream capture and the tools in tools/nx2/debug.
---

# NX2 debug tools

Find a silent fault from a log in minutes.
`tools/nx2/debug/README.md` has the usage of each tool and how to read each census number.
`AGENTS.md` has the accounts, the sources of changes, the build commands, the fair test rules and the Legion Go notes.

## First, read what the log already says

Do this before you make a theory. It takes one minute.

1. Search the log for `<Error>`, `<Critical>` and `Draw skipped`. A line can show once for a fault that repeats on each draw.
2. If a fault shows on one machine only, compare the `Device doesn't support extension` lines of both logs. A missing extension selects another shader path.
3. Force that path on the machine you can debug. `EDEN_NX2_NO_NV_GEOMETRY=1` sends an NVIDIA card down the AMD and Intel path.
4. Show the fault with the bug in (red) and with the fix in (green), on the same path.

Real case, 2026-10-31: on the Legion Go, `Read attribute Generic31Y is not implemented` showed once in each log. We read frames and census numbers for hours first. The Generic31 fix (`9bfb841772`) and the switch proved the cause on an RTX 4080 in 3 runs.

## Steps

1. **Check for a free machine.** Only one heavy emulator runs at a time. `play.ps1` prints `BUSY` and exits with 1 if a game runs. Stop only your own processes, by PID. Do not start a second game.
2. **Build at low priority.** The owner can play at the same time. Run it from PowerShell, not Git Bash:
   ```powershell
   cmd /c "start `"`" /belownormal /wait /b cmd /c `"D:\DEV\egl-compare\build-gui-tip.cmd <worktree>`" > D:\DEV\tmp\build.log 2>&1"
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
- `failed` about equal to `macro_indirect`, and each `0x1e7` draw at zero: a pipeline did not build, and the draws that it should drive read 0. Search for the first `Draw skipped` line and for the exception before it.
- A view that is black in 99.95% of its area while the HUD stays: count it with `black_census.py`. Exactly 0 points to a pass that wrote nothing or a target that cleared, not to a dark scene.

## Find a wrong pixel with RenderDoc

Use this for a bright blob, a black shard or wrong geometry that you can see in a frame.

1. Run with the capture triggers and `ENABLE_VULKAN_RENDERDOC_CAPTURE=1`. Capture a frame that shows the fault.
2. Read the capture with `tools/nx2/debug/rdoc_batch.py`. Go back from the bad pixel, draw by draw, to the first target that holds a bad value.
3. Read the pixels. `GetMinMax` hides NaN and infinite values.
4. At the first bad draw, compare the vertex buffer bytes with guest memory. Old bytes in the host buffer point to the upload path.
5. Count the fault over a whole run with `tools/nx2/debug/halo_count.py <frames> <first> <last> <min percent>`.

## Compare a change inside one run

Add `Common::Nx2Ab::On("<item>")` to the change and run with `EDEN_NX2_AB=4;EDEN_NX2_AB_ITEM=<item>`. Run the same line with an unknown item first. That gives the noise floor. Keep `EDEN_NX2_GPU_PROFILE` off, because its scopes cost time. Evaluate `On` once per draw at most, because side A or B calls the clock. A comparison in one run shows the cost of the change on one scene. It does not show other games.
Read the result with `python -B tools/nx2/debug/ab_means.py <log> <first second>`.

## Traps

- Bananza's key script is timed and blind. Two runs do not reach the same places, so their frame times and black counts do not compare. Compare inside one run. Use Mario Kart World `seed-acc0` to compare between runs.
- More FPS can mean lost draws. Read `failed` and `zero` next to the frame time.
- Settings differ between Deku's GUI and a test. Run `python -B tools/nx2/debug/ini_diff.py <his qt-config.ini> <run>/probe.ini` before you compare his result with yours. The tool does not print paths or keys. Read his file only, and never start a test on his profile.
- `matrix.py` removes each `EDEN_NX2_*` variable from the child. Use `MATRIX_EXTRA_ENV`. A variable set in the parent shell does not reach the game.
- The split GPU thread does not start at `gpu_accuracy=1`, which is the default of `matrix.py`. Use `seed-play-acc0` to run with it. The macro tags take another path there, so test both.
- A higher frame rate can show the same pictures again. Read `Census draws per picture`. A burst of saved frames cannot show this, because a capture that waits drops the next present.
- A 10 s window hides a short event. Use `EDEN_NX2_DRAW_CENSUS_SECONDS=2`.
- `Enabled()` values read at program start cannot see `nx2_switches.txt`, because `main()` reads that file later. Read a new switch at first use.
- A successful `Track` does not prove a mapped store: it follows a loaded pointer to the constant buffer that holds the list. Count the store as lost with `ReachesCbufWithoutLoad`, not with the result of `Track`.
- Edit no source file while Ninja builds: an object can finish after the edit and stay stale. Touch the file after the build if you did.
- Keep test files and run folders on D:. Use isolated profiles. Never copy a real `qt-config.ini`.
