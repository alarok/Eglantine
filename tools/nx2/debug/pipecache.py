"""Read a shader disk cache (vulkan.bin) without the emulator, and compare two of them.

  python pipecache.py <vulkan.bin>                 counts by kind and stage
  python pipecache.py <a/vulkan.bin> <b/vulkan.bin>  what the two files have in common

The compare shows if pipeline keys are stable between boots. Use two caches that the same
executable wrote in the same scene. A pipeline in A and not in B is built again on the next boot.
"""
import struct
import sys
from pathlib import Path

MAGIC = b"yuzucach"
STAGES = ("vertex_b", "tess_ctrl", "tess_eval", "geometry", "fragment", "compute", "vertex_a")
COMPUTE = 5
GEOMETRY = 3
SPH_SIZE = 0x50
GP_PASSTHROUGH_SIZE = 32
COMPUTE_KEY_SIZE = 24
GRAPHICS_HASHES_SIZE = 48
# The offsets of FixedPipelineState. FixedPipelineState::Size() ignores all bytes past the limit.
FIXED_STATE_SIZE = 1008
GRAPHICS_KEY_SIZE = GRAPHICS_HASHES_SIZE + FIXED_STATE_SIZE
OFFSET_ATTACHMENTS = 80
OFFSET_ATTRIBUTES = 112
OFFSET_VERTEX_STRIDES = 368
OFFSET_XFB_STATE = 432
DYNAMIC_STATE_BIT = 0
BLEND_3_BIT = 3
DYNAMIC_VERTEX_BIT = 5
XFB_BIT = 6
FEATURE_BITS = (("eds", 0), ("eds2", 1), ("eds2_logic", 2), ("eds3_blend", 3), ("eds3_enables", 4),
                ("vertex_input", 5), ("color_write", 20))


def key_size(state):
    """Return the number of state bytes that the emulator compares (FixedPipelineState::Size)."""
    raw1 = struct.unpack_from("<I", state)[0]
    if raw1 >> XFB_BIT & 1:
        return FIXED_STATE_SIZE
    if raw1 >> DYNAMIC_VERTEX_BIT & 1 and raw1 >> BLEND_3_BIT & 1:
        return OFFSET_ATTACHMENTS
    if raw1 >> DYNAMIC_VERTEX_BIT & 1:
        return OFFSET_ATTRIBUTES
    if raw1 >> DYNAMIC_STATE_BIT & 1:
        return OFFSET_VERTEX_STRIDES
    return OFFSET_XFB_STATE


class Reader:
    def __init__(self, data):
        self.data = data
        self.at = 0

    def take(self, size):
        if self.at + size > len(self.data):
            raise ValueError(f"file ends at {len(self.data):#x}, need {size:#x} bytes at {self.at:#x}")
        chunk = self.data[self.at:self.at + size]
        self.at += size
        return chunk

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]


def read_environment(reader):
    head = struct.unpack("<5Q7I", reader.take(5 * 8 + 7 * 4))
    code_size, textures, formats, cbufs, replacements = head[:5]
    stage = head[11]
    if stage >= len(STAGES):
        raise ValueError(f"invalid stage {stage} at {reader.at:#x}")
    code = reader.take(code_size)
    # The tables have a 4-byte key, except the cbuf and replacement tables, which have 8 bytes.
    reader.take(textures * 8 + formats * 8 + cbufs * 12 + replacements * 12)
    if stage == COMPUTE:
        reader.take(16)
    else:
        reader.take(SPH_SIZE)
        if stage == GEOMETRY:
            reader.take(GP_PASSTHROUGH_SIZE)
    return {"stage": stage, "code_size": code_size, "cbufs": cbufs, "code": code}


def read_cache(path):
    """Return the pipelines in file order, and the count of bytes that could not be read."""
    reader = Reader(Path(path).read_bytes())
    if reader.take(8) != MAGIC:
        raise ValueError("not a shader disk cache")
    version = reader.u32()
    pipelines = []
    try:
        while reader.at < len(reader.data):
            count = reader.u32()
            if not 1 <= count <= 6:
                raise ValueError(f"invalid environment count {count} at {reader.at - 4:#x}")
            envs = [read_environment(reader) for _ in range(count)]
            raw1 = 0
            if envs[0]["stage"] == COMPUTE:
                key = reader.take(COMPUTE_KEY_SIZE)
            else:
                raw = reader.take(GRAPHICS_KEY_SIZE)
                key = raw[:GRAPHICS_HASHES_SIZE + key_size(raw[GRAPHICS_HASHES_SIZE:])]
                raw1 = struct.unpack_from("<I", key, GRAPHICS_HASHES_SIZE)[0]
            pipelines.append({"key": key, "envs": envs, "compute": envs[0]["stage"] == COMPUTE,
                              "raw1": raw1})
    except ValueError as error:
        print(f"{path}: stops after {len(pipelines)} pipelines: {error}")
    return version, pipelines


def shader_hashes(pipeline):
    if pipeline["compute"]:
        return {pipeline["key"][:8]}
    key = pipeline["key"]
    return {key[i:i + 8] for i in range(0, GRAPHICS_HASHES_SIZE, 8) if any(key[i:i + 8])}


def summarize(path):
    version, pipelines = read_cache(path)
    compute = sum(p["compute"] for p in pipelines)
    print(f"{path}: version {version}, {len(pipelines)} pipelines ({compute} compute, "
          f"{len(pipelines) - compute} graphics)")
    keys = [p["key"] for p in pipelines]
    print(f"  duplicate keys: {len(keys) - len(set(keys))}")
    features = {}
    for pipeline in pipelines:
        if not pipeline["compute"]:
            feature = tuple(name for name, bit in FEATURE_BITS if pipeline["raw1"] >> bit & 1)
            features[feature] = features.get(feature, 0) + 1
    # The emulator skips a pipeline at boot if its features are not those of the device.
    for feature, count in sorted(features.items(), key=lambda item: -item[1]):
        print(f"  {count} graphics pipelines with: {' '.join(feature)}")
    shaders = set().union(*(shader_hashes(p) for p in pipelines)) if pipelines else set()
    print(f"  distinct shaders: {len(shaders)}")
    return pipelines


def state_difference(a_key, b_key):
    """Name the first differing state bytes of two pipelines that use the same shaders."""
    a_state = a_key[GRAPHICS_HASHES_SIZE:]
    b_state = b_key[GRAPHICS_HASHES_SIZE:]
    offsets = [i for i in range(min(len(a_state), len(b_state))) if a_state[i] != b_state[i]]
    return (offsets[0] // 4 * 4) if offsets else -1


def compare(path_a, path_b):
    a = summarize(path_a)
    b = summarize(path_b)
    a_keys = {p["key"] for p in a}
    b_keys = {p["key"] for p in b}
    a_shaders = set().union(*(shader_hashes(p) for p in a)) if a else set()
    b_shaders = set().union(*(shader_hashes(p) for p in b)) if b else set()
    print(f"same pipeline key: {len(a_keys & b_keys)} of A {len(a_keys)}, B {len(b_keys)}")
    print(f"same shader hash:  {len(a_shaders & b_shaders)} of A {len(a_shaders)}, B {len(b_shaders)}")
    # A shader with the same code and another hash has an unstable hash, or changed its state.
    by_shaders = {}
    for pipeline in a:
        if not pipeline["compute"]:
            by_shaders.setdefault(pipeline["key"][:GRAPHICS_HASHES_SIZE], []).append(pipeline["key"])
    offsets = {}
    new_shaders = 0
    for pipeline in b:
        if pipeline["compute"] or pipeline["key"] in a_keys:
            continue
        same = by_shaders.get(pipeline["key"][:GRAPHICS_HASHES_SIZE])
        if same is None:
            new_shaders += 1
            continue
        offset = state_difference(same[0], pipeline["key"])
        offsets[offset] = offsets.get(offset, 0) + 1
    print(f"B graphics keys that A does not have: {new_shaders} with other shaders, "
          f"{sum(offsets.values())} with the same shaders and other state")
    for offset, count in sorted(offsets.items(), key=lambda item: -item[1])[:12]:
        print(f"  state offset {offset:#x}: {count}")


def main():
    if len(sys.argv) == 2:
        summarize(sys.argv[1])
    elif len(sys.argv) == 3:
        compare(sys.argv[1], sys.argv[2])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
