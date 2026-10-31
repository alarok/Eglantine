# NX2 debug tools

These scripts help to debug the Switch 2 (NX2) emulator offline.
Most of them read a log or a capture file. They do not start the emulator.
Only `play.ps1` and `matrix.py` start it.

## Rules for tests

- Use an isolated profile for each test run. `matrix.py` makes one.
- Run only one heavy emulator at a time. `play.ps1` stops with `BUSY` if one runs.
- Never copy a real `qt-config.ini`. `matrix.py` writes its own `probe.ini` and copies no config file.
- Keep temporary files and run folders off the system drive.

## Environment variables of the emulator

- `EDEN_NX2_PB_CAPTURE=<file>` writes a pushbuffer capture. The emulator writes it at the first sign of a broken stream.
  Add `EDEN_NX2_PB_CAPTURE_AFTER=<n>` to write it after `<n>` parsed entries instead.
- `EDEN_NX2_DRAW_CENSUS=1` writes a census block to the log every 10 s (log channel `HW.GPU`).
  It also writes `Lost shader stores:` lines and one `Census image:` line for each image with no device memory.
  `EDEN_NX2_DRAW_CENSUS_SECONDS=<n>` changes the 10 s window. Use a short window to find a short event.
- The GUI reads these names from `nx2_switches.txt`. A variable in the real environment wins.
- `matrix.py` removes every `EDEN_NX2_*` variable from the child environment.
  To pass one, set `MATRIX_EXTRA_ENV="NAME=value;NAME=value"`.
  Example: `MATRIX_EXTRA_ENV="EDEN_NX2_DRAW_CENSUS=1"`.

## How to read the census

A draw that draws nothing shows no error. Only these counts show it.

- `Census draws`: `macro_indirect` counts the draws of macros that got a draw record. A record is a small command entry that points at words the GPU wrote. `api_indirect` counts host indirect draws. The census does not read their counts.
- `Census zero draws`: draws with 0 vertices or 0 copies. A record with 0 triangles usually gives a zero draw. This is normal for a mesh that culling removed.
- `macro_record_no_draw`: macros that got a record and drew nothing. A record with 0 copies gives this, because the macro has no copy to draw.
- `Census top macros`: the macros with the most of these counts. The number is the macro's start position, as in the `Native MME` log lines.
- `failed` and `predicate_off`: the rasterizer dropped the draw, or the render condition dropped it.
- `Census images`: sampled images with no device memory, and the draws that sample them. A `Census image:` line gives the address, the size and the format of each one.
- `Lost shader stores`: a program that writes through an address the recompiler cannot map. Usually the address was loaded from memory. The store writes nothing.

Example: Bananza's terrain with `EDEN_NX2_RESETFIX=0`. The terrain is black. `macro_indirect` falls from about 110000 per 10 s to 0, and macro `0x1e7` shows about 135000 `no_draw` per 10 s. The lost store line names the program that should reset the records.
Compare a good run and a bad run with `logdiff.py`. Do not read one run alone: a count is only strange when you can compare it.

## Capture tools (read a `EDEN_NX2_PB_CAPTURE` file)

The first line of a capture holds the reason. Each next line is one pushbuffer entry.

- `pbdecode.py`: use it first, to find where the stream breaks.
  `python pbdecode.py <capture> [--around N]`
- `pbflags.py`: use it to see the `gpu_written` and `changed` flags by memory region.
  `python pbflags.py <capture> [last-N-to-print]`
- `pbstale.py`: use it to find entries that hold the same words as the last visit of the same address.
  `python pbstale.py <capture> [last-N-to-print]`
- `pbslices.py`: use it to list the entries of one memory region, each with the entry before it.
  `python pbslices.py <capture> <address-prefix-hex> <shift> [max]`
- `pbshift.py`: use it to print the ring words around the entry where the unit alignment shifts.
  `python pbshift.py <capture> <i1,i2,...> <from-to> <address-hex>`
- `pbkshift.py`: use it to find the word shift between the first changed dispatch block and the good block before it.
  `python pbkshift.py <capture>`

## Log tools

- `logdiff.py`: use it to compare two runs. It shows error line counts, frame times, census totals and lost shader stores.
  `python logdiff.py <run-a-log> <run-b-log>`
- `session.ps1`: use it for a quick summary of one log: error counts, last frame times and GPU memory.
  `powershell -File session.ps1 -Log <eden_log.txt>`

## Shader cache tools

- `pipecache.py`: use it to read a shader disk cache (`vulkan.bin`) without the emulator. It counts pipelines and groups them by device features. With two files it shows the keys they share, and how the other keys differ.
  `python pipecache.py <vulkan.bin> [<other vulkan.bin>]`

## Process tools

- `threads.py`: use it to see the CPU use of each thread of a running process.
  `python threads.py <exe-name> [delay-s] [window-s] [repeats]`
- `symbolize.py`: use it to name an offset of `eden-cli.exe` with its PDB. It needs Windows `dbghelp`.
  `python symbolize.py <exe> <pdb-dir> <offset> [<offset> ...]`

## Run tools (start the emulator)

- `matrix.py`: use it to run one game with isolated profiles, one variant after the other.
  Each variant changes one setting. It saves the last frame of each run.
  `python matrix.py --root <dir> --exe <eden-cli.exe> --game <exefs main> [--seconds N] [--keys-from <dir>] [--real-profile <dir>] [--firmware <dir>] [--nand-from <dir>] <variant> ...`
  A variant that needs a source folder fails at the start if you give no folder.
  Each folder option can also come from `MATRIX_KEYS_FROM`, `MATRIX_REAL_PROFILE`, `MATRIX_FIRMWARE` or `MATRIX_NAND_FROM`.
  `--keys-from` is the folder that holds the key files. The script copies it into the run and deletes the copy after the run.
- `play.ps1`: use it to play one game for a long time with a scripted controller. It calls `matrix.py` and `thumbs.py`.
  `powershell -File play.ps1 <eden-cli.exe> <label> <game> [seconds] [variant] -OutDir <dir> [-GamesFile <file>]`
  `<game>` is a key in the games file. The file is `games.local.json` next to the script, or the `-GamesFile` path.
  Git ignores `games.local.json`. Do not commit it. Its shape is:
  `{"bananza": "<path to exefs main>", "mkw": "<path to exefs main>"}`
- `thumbs.py`: use it to make a labelled thumbnail grid of the captured frames of a run. `play.ps1` calls it.
  `python thumbs.py <frames-dir> <output.png>`
