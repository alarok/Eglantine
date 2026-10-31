"""Compare the video frames of a run with a reference decoder, without the game.

Run the game with EDEN_NX2_VDEC_DUMP=<dir>. The emulator then writes nx2-vdec-<n>.ivf (the
compressed frames from the game) and nx2-vdec-<n>.nv12 (the planes that it gives to the game).

Usage: python vdec_compare.py <dump dir> [movie dir] [--size 960x540]

For each stream the tool does three checks:
1. Input: finds the movie with the same first frame in <movie dir> (.webm files of the game) and
   compares each compressed frame. A difference means that the game or the IPC read changed it.
2. Decode: decodes the .ivf with the ffmpeg command line and compares each frame with the .nv12.
3. It saves the first different frame as a picture: emulator on top, reference below.

Needs ffmpeg and ffprobe on the PATH, numpy and Pillow.
"""
import argparse
import pathlib
import struct
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image


def read_ivf(path):
    data = path.read_bytes()
    width, height = struct.unpack_from("<HH", data, 12)
    frames = []
    at = struct.unpack_from("<H", data, 6)[0]
    while at + 12 <= len(data):
        size = struct.unpack_from("<I", data, at)[0]
        frames.append(data[at + 12 : at + 12 + size])
        at += 12 + size
    return width, height, frames


def webm_frames(path, work):
    out = pathlib.Path(work) / "movie.ivf"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-c", "copy", "-f", "ivf", str(out)], check=True)
    return read_ivf(out)[2]


def check_input(frames, movie_dir, work):
    if movie_dir is None:
        return
    for movie in sorted(movie_dir.glob("*.webm")):
        expected = webm_frames(movie, work)
        if expected and expected[0] == frames[0]:
            different = [i for i, (a, b) in enumerate(zip(frames, expected)) if a != b]
            print(f"  movie {movie.name}: {len(frames)} inputs, movie has {len(expected)}, different {len(different)} {different[:12]}")
            return
    print("  input: no movie has the same first frame")


def to_rgb(frame, width, height):
    luma = frame[: width * height].reshape(height, width).astype(np.float32)
    chroma = frame[width * height :].reshape((height + 1) // 2, width // 2, 2).astype(np.float32)
    chroma = chroma.repeat(2, axis=0)[:height].repeat(2, axis=1)
    y = (luma - 16) * 1.164
    u = chroma[..., 0] - 128
    v = chroma[..., 1] - 128
    rgb = np.stack([y + 1.596 * v, y - 0.392 * u - 0.813 * v, y + 2.017 * u], axis=-1)
    return np.clip(rgb, 0, 255).astype(np.uint8)


def check_decode(ivf, nv12, width, height, out_dir):
    frame_size = width * height * 3 // 2
    reference = subprocess.run(
        ["ffmpeg", "-v", "error", "-threads", "1", "-i", str(ivf), "-f", "rawvideo", "-pix_fmt", "nv12", "-"],
        check=True, capture_output=True).stdout
    ours = np.fromfile(nv12, dtype=np.uint8)
    theirs = np.frombuffer(reference, dtype=np.uint8)
    count_ours = len(ours) // frame_size
    count_theirs = len(theirs) // frame_size
    print(f"  frames: emulator {count_ours}, reference {count_theirs}")
    bad = []
    saved = False
    for index in range(min(count_ours, count_theirs)):
        a = ours[index * frame_size : (index + 1) * frame_size]
        b = theirs[index * frame_size : (index + 1) * frame_size]
        if np.array_equal(a, b):
            continue
        difference = np.abs(a[: width * height].astype(int) - b[: width * height].astype(int)).reshape(height, width)
        rows, cols = np.nonzero(difference > 8)
        box = (cols.min(), rows.min(), cols.max(), rows.max()) if len(rows) else None
        bad.append((index, int((a != b).sum()), box))
        if not saved:
            picture = np.vstack([to_rgb(a, width, height), to_rgb(b, width, height)])
            name = out_dir / f"{nv12.stem}-frame{index:04}.png"
            Image.fromarray(picture).save(name)
            print(f"  first different frame saved: {name}")
            saved = True
    print(f"  different frames: {len(bad)}")
    for index, count, box in bad[:12]:
        print(f"    frame {index}: {count} bytes, luma box over 8 levels {box}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dump", type=pathlib.Path)
    parser.add_argument("movies", type=pathlib.Path, nargs="?")
    args = parser.parse_args()
    streams = sorted(args.dump.glob("nx2-vdec-*.ivf"))
    if not streams:
        sys.exit("no nx2-vdec-*.ivf files")
    with tempfile.TemporaryDirectory(dir=args.dump) as work:
        for ivf in streams:
            width, height, frames = read_ivf(ivf)
            nv12 = ivf.with_suffix(".nv12")
            print(f"{ivf.name}: {width}x{height}, {len(frames)} inputs")
            if not frames:
                continue
            check_input(frames, args.movies, work)
            if nv12.exists():
                check_decode(ivf, nv12, width, height, args.dump)
            else:
                print("  no .nv12 file")


if __name__ == "__main__":
    main()
