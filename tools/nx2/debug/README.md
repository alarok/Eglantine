# NX2 debug tools

These scripts help to debug the Switch 2 (NX2) emulator offline.
Most of them read a log or a capture file. They do not start the emulator.
Only `play.ps1` and `matrix.py` start it.

## Rules for tests

- Use an isolated profile for each test run. `matrix.py` makes one.
- Run only one heavy emulator at a time. `play.ps1` stops with `BUSY` if one runs.
- Never copy a real `qt-config.ini`. `matrix.py` writes its own `probe.ini` and copies no config file.
- Keep temporary files and run folders off the system drive.

## Profiling one thread

- `rip_sampler.py <exe> <thread> <exe-with-pdb> <pdb-dir> [delay-s] [seconds] [hz]` samples the
  instruction pointer of one thread and prints the modules, the functions and three buckets:
  blocking wait, spin, and the rest. It loads symbols for every module, including `ntdll.dll` and
  `win32u.dll` from the Microsoft symbol server, so a system wait gets a name instead of a module.
  It needs the dbghelp of the Debugging Tools folder (set `DBGHELP_DIR`) and `symsrv.dll` beside it;
  the dbghelp of Windows cannot download. Cache: `SYM_CACHE`.
  It prints samples per symbol and does not unwind, so it cannot say which of our functions called
  a wait.
- `stack_sampler.py <exe> <thread> <pdb-dir> [delay-s] [seconds] [hz]` walks the stack with
  `StackWalk64` while the thread is suspended, so it reports exclusive and inclusive time per
  function, and which of our functions was on the stack under a system wait. Use it for a question
  like "who calls Sleep". It is slower, so use a lower rate.
- `thread_cpu.ps1 [-ProcessName eden-cli] [-Delay 0] [-Window 70]` prints the CPU seconds per wall
  second of the whole process and the thread ids above 5 % of one core. It names no thread.

Two traps found with these tools: an interval counted as "work" can be a spin (`GpuSplit::Drain`),
and a percentage of samples is not a share of the frame time.

## Environment variables of the emulator

- `EDEN_NX2_PB_CAPTURE=<file>` writes a pushbuffer capture. The emulator writes it at the first sign of a broken stream.
  Add `EDEN_NX2_PB_CAPTURE_AFTER=<n>` to write it after `<n>` parsed entries instead.
- `EDEN_NX2_DRAW_CENSUS=1` writes a census block to the log every 10 s (log channel `HW.GPU`).
  It also writes `Lost shader stores:` lines and one `Census image:` line for each image with no device memory.
  `EDEN_NX2_DRAW_CENSUS_SECONDS=<n>` changes the 10 s window. Use a short window to find a short event.
- `EDEN_NX2_VDEC_DUMP=<dir>` writes each `nx2:vdecsvc` movie as an IVF file (input) and an NV12 file (output).
  The log gets `changed while the game had it` if guest memory of a decoded image changes before the decoder uses it again.
- `EDEN_NAN_OUTPUTS=magenta|zero|big` replaces NaN or infinite float color outputs. Use an empty shader cache.
- `EDEN_RENDERDOC_DLL=<renderdoc.dll>` loads RenderDoc at the start. Also set `ENABLE_VULKAN_RENDERDOC_CAPTURE=1`, or the layer stays off.
  `EDEN_RENDERDOC_PATH=<template>` sets the path of the capture files.
- `EDEN_NX2_RDOC_PRESENTS=<n>[,<n>...]` makes one RenderDoc capture from present `n` to present `n+2`. Keep the numbers at least 3 apart.
- `EDEN_NX2_FRAME_CAPTURE_EVERY=<n>` changes the interval of the saved frames from 120 presents.
- `EDEN_NX2_FRAME_CAPTURE_BURST=<n>` saves the first `n` presents of each interval. Only about every second present is saved, because a capture that waits drops the next one. A burst cannot show repeated pictures. Use `Census draws per picture` for that.
- `EDEN_NX2_NO_NV_GEOMETRY=1` hides `VK_NV_geometry_shader_passthrough`, `VK_NV_viewport_array2` and `VK_NV_viewport_swizzle`. An NVIDIA card then takes the shader paths of AMD and Intel. Use an empty shader cache.
- `EDEN_NX2_KEEP_ASTC=1` turns off the BC3 texture mode that low VRAM selects.
- `EDEN_NX2_VRAM_LIMIT_MIB=<n>` treats each device-local heap as `<n>` MiB, to test a smaller card.
- `EDEN_NX2_BUFFER_DOWNLOADS=0` or `1` overrides the default for the buffer copy back at fences. Only Pokopia has it on by default.
- `EDEN_NX2_AB=<s>` with `EDEN_NX2_AB_ITEM=<item>` switches `Common::Nx2Ab::On(<item>)` every `<s>` seconds. Item `none` gives the noise.
- `EDEN_NX2_GPU_PROFILE=1` writes the share of each GPU thread zone to the log every 10 s. It makes frames slower.
- The GUI reads these names from `nx2_switches.txt`. A variable in the real environment wins.
- `matrix.py` removes every `EDEN_NX2_*` variable from the child environment.
  To pass one, set `MATRIX_EXTRA_ENV="NAME=value;NAME=value"`.
  Example: `MATRIX_EXTRA_ENV="EDEN_NX2_DRAW_CENSUS=1"`.

## How to read the census

A draw that draws nothing shows no error. Only these counts show it.

- `Census draws`: `macro_indirect` counts the draws of macros that got a draw record. A record is a small command entry that points at words the GPU wrote. `api_indirect` counts host indirect draws. The census does not read their counts.
- `Census draws per picture`: the draws between pictures, for 16 pictures in a row at each 600. A picture with 0 draws shows no new work, so a higher present rate can mean the same pictures again.
- `Census zero draws`: draws with 0 vertices or 0 copies. A record with 0 triangles usually gives a zero draw. This is normal for a mesh that culling removed.
- `macro_record_no_draw`: macros that got a record and drew nothing. A record with 0 copies gives this, because the macro has no copy to draw.
- `Census top macros`: the macros with the most of these counts. The number is the macro's start position, as in the `Native MME` log lines.
- `failed` and `predicate_off`: the rasterizer dropped the draw, or the render condition dropped it. `failed` has no log limit, but the `Draw skipped` line shows once per shader pair. A high `failed` with one error line is one bad pipeline on each draw.
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

- `logdiff.py`: use it to compare two runs. It shows errors, native shader rejections by opcode, frame times, census totals and lost shader stores. Rejection lines do not count failed draws.
  `python logdiff.py <run-a-log> <run-b-log>`
- `session.ps1`: use it for a quick summary of one log: error counts, last frame times and GPU memory.
  `powershell -File session.ps1 -Log <eden_log.txt>`
- `vdec_compare.py`: use it to check a `EDEN_NX2_VDEC_DUMP` folder. It compares the inputs with the `.webm` packets and the frames with FFmpeg output.
  It saves the first different frame. A result of 0 different frames proves that the decoder is correct and the fault is after it.
  `python vdec_compare.py <dump dir> [movie dir]`
- `ab_means.py`: use it to read the `nx2 A/B` rows of a log. It prints the frame time of each side after a start time. With item `none`, the difference is the noise.
  `python ab_means.py <log> [first second]`
- `vram_series.py`: use it to print the texture cache, heap and frame lines of a log as one table.
  `python vram_series.py <log> [every]`
- `ini_diff.py`: use it to print the settings that differ between two config files. It does not print paths, names or keys.
  `python ini_diff.py <a.ini> <b.ini>`

## Frame tools (read saved `.tga` frames, and need Pillow)

- `black_census.py`: use it to count frames with a black 3D view and a lit HUD, for each run under a folder. It also prints the settings of the run from `probe.ini`.
  `python black_census.py <folder>`
- `frame_luma.py`: use it to print the brightness of the middle of each frame.
  `python frame_luma.py <frames-dir> [every]`

## Shader cache tools

- `pipecache.py`: use it to read a shader disk cache (`vulkan.bin`) without the emulator. It counts pipelines and groups them by device features. With two files it shows the keys they share, and how the other keys differ.
  `python pipecache.py <vulkan.bin> [<other vulkan.bin>]`

## Native shader dumps

- `native_lower_replay.exe`: read one local dump from `EDEN_NX2_SHADER_DUMP` and run `LowerToMaxwell` offline. It does not run the GPU or verify pixels.
  In a Visual Studio developer prompt, run `cl /nologo /std:c++20 /EHsc /Isrc tools/nx2/debug/native_lower_replay.cpp /Fo:D:\DEV\tmp\native_lower_replay.obj /Fe:D:\DEV\tmp\native_lower_replay.exe`.
  Then run `D:\DEV\tmp\native_lower_replay.exe D:\DEV\tmp\shader.bin`.
  Exit code 0 means the lowerer accepted the program, 1 means it rejected the program, and 2 means the file is invalid.
  Keep game shader dumps outside Git.

## RenderDoc tools

- `rdoc_batch.py`: use it to read a RenderDoc capture with no manual work. It runs in the Python of RenderDoc. The header of the file lists the commands.
  `set RDOC_CAP=<file.rdc>`, `set RDOC_OUT=<folder>`, `set RDOC_COMMANDS=summary|scan 1 200000 200`, then `qrenderdoc.exe --python rdoc_batch.py`.
  `qrenderdoc` opens a window. Run it on a hidden desktop.
- `halo_count.py`: use it to find saved frames with large white areas.
  `python halo_count.py <frames-dir> [first] [last] [min-percent]`

## Process tools

- `commitwatch.py`: record a process's private commit, shared commit, working set, and system commit.
  `python commitwatch.py <process.json|pid> <out.csv> [--every S] [--survey-every S] [--seconds N]`
  The optional address-space survey can stall the process. Set `--survey-every 0` for frame-time tests.
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
