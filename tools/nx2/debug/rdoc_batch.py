"""Read a RenderDoc capture with no manual work. RenderDoc runs this script in its own Python.

Usage (from a hidden desktop, because qrenderdoc opens a window):
    set RDOC_CAP=<capture.rdc>
    set RDOC_OUT=<empty folder>
    set RDOC_COMMANDS=<one command per line>
    qrenderdoc.exe --python rdoc_batch.py

Commands:
    summary                     Write actions.txt and textures.txt.
    usage <resource>            Print each event that uses this resource.
    state <event>               Print the shaders, the inputs and the outputs at this event.
    save <event> [resource]     Save the outputs at this event as PNG, or one resource.
    history <resource> <x> <y>  Print each event that changes this pixel.
    shader <event>              Write the pixel shader disassembly to a file.
    draw <event>                Print the counts and the state of this draw.
    scan <first> <last> [limit] Print the float targets that hold values over the limit.
    minmax <event> <resource>   Print the range of each mip at this event.
    trace <resource> [mip]      Print the highest value after each event that writes this resource.
    cbuf <event> [count]        Print the first floats of the pixel shader constant buffers.
    nanmap <event> <resource>   Print the NaN and infinite pixels of an R11G11B10 resource.
    nanfind <resource> <first> <last> [nan_only]  Find the first action that leaves such pixels.
    debugnan <event> <x> <y> [limit]  Debug the pixel shader at one pixel. Print the first NaN steps.
    postvs <event> [limit]      Print the vertices with NaN outputs. Debug the first one.
    vinputs <event> [first] [count]  Print the vertex layout and the raw vertex data of a draw.
    bufwatch <buffer> <offset> <size> [stride]  Print each use of a buffer that changes these bytes.
    copies <first> <last>       Print the source and the destination of each copy.
    mips <event> <resource>     Save each mip at this event.
A resource is a number from textures.txt. RDOC_OUT receives report.txt. A failed command writes its
error to report.txt, and the next command runs.
"""
import os
import struct
import traceback

import renderdoc as rd

OUT = os.environ["RDOC_OUT"]
report = open(os.path.join(OUT, "report.txt"), "a")


def say(text):
    report.write(str(text) + "\n")
    report.flush()


def rid_number(rid):
    return int(rid)


def walk(actions):
    for action in actions:
        yield action
        for child in walk(action.children):
            yield child


class Session:
    def __init__(self, controller):
        self.controller = controller
        self.structured = controller.GetStructuredFile()
        self.textures = {rid_number(t.resourceId): t for t in controller.GetTextures()}
        self.names = {rid_number(r.resourceId): r.name for r in controller.GetResources()}

    def texture_text(self, number):
        tex = self.textures.get(number)
        if tex is None:
            return "%d (%s)" % (number, self.names.get(number, "?"))
        return "%d %dx%d mips %d layers %d %s" % (number, tex.width, tex.height, tex.mips, tex.arraysize,
                                                  tex.format.Name())

    def summary(self):
        with open(os.path.join(OUT, "actions.txt"), "w") as out:
            counts = {}
            for action in walk(self.controller.GetRootActions()):
                name = action.GetName(self.structured)
                outputs = [rid_number(o) for o in action.outputs if rid_number(o) != 0]
                out.write("%d %s outputs %s depth %d\n" % (action.eventId, name, outputs,
                                                          rid_number(action.depthOut)))
                key = name.split("(")[0]
                counts[key] = counts.get(key, 0) + 1
        say("action counts: %s" % sorted(counts.items(), key=lambda item: -item[1])[:20])
        with open(os.path.join(OUT, "textures.txt"), "w") as out:
            for number in sorted(self.textures):
                uses = self.controller.GetUsage(self.textures[number].resourceId)
                out.write("%s uses %d\n" % (self.texture_text(number), len(uses)))
        say("textures: %d" % len(self.textures))

    def usage(self, number):
        tex = self.textures[number]
        say("--- usage of %s" % self.texture_text(number))
        for use in self.controller.GetUsage(tex.resourceId):
            say("  %d %s" % (use.eventId, str(use.usage).split(".")[-1]))

    def state(self, event):
        self.controller.SetFrameEvent(event, True)
        pipe = self.controller.GetPipelineState()
        say("--- state at %d" % event)
        for stage in (rd.ShaderStage.Vertex, rd.ShaderStage.Pixel, rd.ShaderStage.Compute):
            shader = pipe.GetShader(stage)
            if rid_number(shader) == 0:
                continue
            say("  %s shader %d" % (str(stage).split(".")[-1], rid_number(shader)))
            for used in pipe.GetReadOnlyResources(stage, True):
                number = rid_number(used.descriptor.resource)
                if number:
                    say("    read %d: %s view format %s first mip %d" % (
                        used.access.index, self.texture_text(number), used.descriptor.format.Name(),
                        used.descriptor.firstMip))
            for used in pipe.GetReadWriteResources(stage, True):
                number = rid_number(used.descriptor.resource)
                if number:
                    say("    write %d: %s view format %s" % (used.access.index, self.texture_text(number),
                                                             used.descriptor.format.Name()))
        for index, target in enumerate(pipe.GetOutputTargets()):
            number = rid_number(target.resource)
            if number:
                say("  output %d: %s view format %s" % (index, self.texture_text(number), target.format.Name()))

    def shader(self, event):
        """Write the disassembly of the pixel shader at this event to a file."""
        self.controller.SetFrameEvent(event, True)
        pipe = self.controller.GetPipelineState()
        reflection = pipe.GetShaderReflection(rd.ShaderStage.Pixel)
        target = self.controller.GetDisassemblyTargets(True)[0]
        text = self.controller.DisassembleShader(pipe.GetGraphicsPipelineObject(), reflection, target)
        path = os.path.join(OUT, "ps-ev%06d.txt" % event)
        with open(path, "w") as out:
            out.write(text)
        say("wrote %s (%d lines)" % (path, text.count("\n")))

    def draw(self, event):
        """Print the counts and the state that decide which pixels this draw touches."""
        action = self.controller.GetAction(event) if hasattr(self.controller, "GetAction") else None
        if action is None:
            for item in walk(self.controller.GetRootActions()):
                if item.eventId == event:
                    action = item
                    break
        say("--- draw %d: indices %d instances %d" % (event, action.numIndices, action.numInstances))
        self.controller.SetFrameEvent(event, True)
        pipe = self.controller.GetPipelineState()
        topology = pipe.GetPrimitiveTopology()
        say("  topology %s" % topology)
        for index, view in enumerate(pipe.GetViewportScissor().viewports if hasattr(pipe, "GetViewportScissor") else []):
            say("  viewport %d: %s" % (index, view))
        vk = self.controller.GetVulkanPipelineState()
        say("  viewport %s" % [(v.vp.x, v.vp.y, v.vp.width, v.vp.height) for v in vk.viewportScissor.viewportScissors][:1])
        say("  scissor %s" % [(v.scissor.x, v.scissor.y, v.scissor.width, v.scissor.height) for v in vk.viewportScissor.viewportScissors][:1])
        for index, blend in enumerate(vk.colorBlend.blends):
            say("  blend %d enabled %s mask %#x" % (index, blend.enabled, blend.writeMask))
        for used in pipe.GetReadOnlyResources(rd.ShaderStage.Pixel, True):
            say("  sampler for %d: %s" % (used.access.index, used.descriptor.resource))
        samplers = pipe.GetSamplers(rd.ShaderStage.Pixel, True)
        for used in samplers:
            sampler = used.sampler
            say("  sampler %d: filter %s/%s/%s address %s %s" % (
                used.access.index, sampler.filter.minify, sampler.filter.magnify, sampler.filter.mip,
                sampler.addressU, sampler.addressV))
        mesh = self.controller.GetPostVSData(0, 0, rd.MeshDataStage.VSOut)
        say("  post vs: vertices %d stride %d" % (mesh.numIndices, mesh.vertexByteStride))
        if mesh.numIndices and mesh.vertexResourceId != rd.ResourceId.Null():
            data = self.controller.GetBufferData(mesh.vertexResourceId, mesh.vertexByteOffset,
                                                 mesh.vertexByteStride * min(mesh.numIndices, 8))
            for index in range(min(mesh.numIndices, 8)):
                start = index * mesh.vertexByteStride
                say("    %s" % (struct.unpack_from("<4f", data, start),))

    def scan(self, first, last, limit=100):
        """Print the targets in this event range that hold values over the limit, or Inf, or NaN."""
        say("--- scan %d to %d, limit %d" % (first, last, limit))
        checked = 0
        for action in walk(self.controller.GetRootActions()):
            event = action.eventId
            if not first <= event <= last:
                continue
            name = action.GetName(self.structured)
            targets = []
            if "EndRenderPass" in name:
                targets = [rid_number(o) for o in action.outputs if rid_number(o) != 0]
            elif action.flags & rd.ActionFlags.Dispatch:
                self.controller.SetFrameEvent(event, True)
                pipe = self.controller.GetPipelineState()
                targets = [rid_number(used.descriptor.resource)
                           for used in pipe.GetReadWriteResources(rd.ShaderStage.Compute, True)]
            for number in targets:
                tex = self.textures.get(number)
                if tex is None or "FLOAT" not in tex.format.Name():
                    continue
                self.controller.SetFrameEvent(event, True)
                sub = rd.Subresource(0, 0, 0)
                low, high = self.controller.GetMinMax(tex.resourceId, sub, rd.CompType.Typeless)
                checked += 1
                values = list(high.floatValue)[:3] + list(low.floatValue)[:3]
                odd = [v for v in values if v != v or abs(v) > limit]
                if odd:
                    say("  %d %s: %s max %s min %s" % (event, name[:24], self.texture_text(number),
                                                       list(high.floatValue)[:4], list(low.floatValue)[:4]))
        say("  checked %d targets" % checked)

    def minmax(self, event, number):
        """Print the lowest and highest values of each mip of this resource at this event."""
        self.controller.SetFrameEvent(event, True)
        tex = self.textures[number]
        say("--- minmax of %s at %d" % (self.texture_text(number), event))
        for mip in range(tex.mips):
            low, high = self.controller.GetMinMax(tex.resourceId, rd.Subresource(mip, 0, 0), rd.CompType.Typeless)
            say("  mip %d max %s min %s" % (mip, list(high.floatValue)[:4], list(low.floatValue)[:4]))

    def trace(self, number, mip=0):
        """Print the highest value of this resource after each event that writes it."""
        tex = self.textures[number]
        say("--- trace of %s, mip %d" % (self.texture_text(number), mip))
        last = None
        for use in self.controller.GetUsage(tex.resourceId):
            kind = str(use.usage).split(".")[-1]
            if kind not in ("ColorTarget", "CS_RWResource", "PS_RWResource", "CopyDst", "ResolveDst", "Clear",
                            "GenMips"):
                continue
            self.controller.SetFrameEvent(use.eventId, True)
            sub = rd.Subresource(mip, 0, 0)
            low, high = self.controller.GetMinMax(tex.resourceId, sub, rd.CompType.Typeless)
            now = list(high.floatValue)[:3]
            if now != last:
                say("  %d %s max %s min %s" % (use.eventId, kind, now, list(low.floatValue)[:3]))
            last = now

    def cbuf(self, event, count=32):
        """Print the first floats of each constant buffer of the pixel shader at this event."""
        self.controller.SetFrameEvent(event, True)
        pipe = self.controller.GetPipelineState()
        say("--- constant buffers at %d" % event)
        for used in pipe.GetConstantBlocks(rd.ShaderStage.Pixel, True):
            descriptor = used.descriptor
            if rid_number(descriptor.resource) == 0:
                continue
            data = self.controller.GetBufferData(descriptor.resource, descriptor.byteOffset, count * 4)
            values = struct.unpack("<%df" % (len(data) // 4), data[:len(data) // 4 * 4])
            say("  slot %d: %s" % (used.access.index, ["%.5g" % value for value in values]))

    def broken_pixels(self, number, event):
        """Return the NaN pixels and the infinite pixels of an R11G11B10 resource at this event."""
        tex = self.textures[number]
        self.controller.SetFrameEvent(event, True)
        data = self.controller.GetTextureData(tex.resourceId, rd.Subresource(0, 0, 0))
        nans = []
        infs = []
        for index, (value,) in enumerate(struct.iter_unpack("<I", data)):
            if value & 0x7C0 == 0x7C0 or value & 0x1F0000 == 0x1F0000 or value & 0xF8000000 == 0xF8000000:
                r, g, b = value & 0x7FF, (value >> 11) & 0x7FF, value >> 22
                odd = (r >= 0x7C0 and r & 0x3F) or (g >= 0x7C0 and g & 0x3F) or (b >= 0x3E0 and b & 0x1F)
                (nans if odd else infs).append(index)
        return nans, infs

    def nanmap(self, event, number):
        """Print the count and the place of the NaN and infinite pixels of a resource at this event."""
        width = self.textures[number].width
        nans, infs = self.broken_pixels(number, event)
        say("--- %s at %d: nan %d, inf %d" % (self.texture_text(number), event, len(nans), len(infs)))
        for name, pixels in (("nan", nans), ("inf", infs)):
            if pixels:
                xs = [index % width for index in pixels]
                ys = [index // width for index in pixels]
                say("  %s box %d %d to %d %d, samples %s" % (
                    name, min(xs), min(ys), max(xs), max(ys),
                    [(index % width, index // width) for index in pixels[:: max(1, len(pixels) // 6)]][:6]))

    def nanfind(self, number, first, last, nan_only=0):
        """Find the first action in this event range after which a resource holds NaN or infinite pixels.

        With nan_only set, the search ignores infinite pixels.
        """
        events = [action for action in walk(self.controller.GetRootActions()) if first <= action.eventId <= last]
        low, high = 0, len(events) - 1
        say("--- nanfind %s, %d actions" % (self.texture_text(number), len(events)))
        while low < high:
            middle = (low + high) // 2
            nans, infs = self.broken_pixels(number, events[middle].eventId)
            say("  %d: nan %d, inf %d" % (events[middle].eventId, len(nans), len(infs)))
            if nans or (infs and not nan_only):
                high = middle
            else:
                low = middle + 1
        say("  first: %d %s" % (events[low].eventId, events[low].GetName(self.structured)[:60]))
        self.nanmap(events[low].eventId, number)

    def debugnan(self, event, x, y, limit=12):
        """Debug the pixel shader of this event at one pixel. Print the first steps that make NaN or Inf."""
        self.controller.SetFrameEvent(event, True)
        trace = self.controller.DebugPixel(x, y, rd.DebugPixelInputs())
        if trace.debugger is None:
            say("--- debugnan %d %d %d: no debugger, %s" % (event, x, y, "the pixel has no hit or no support"))
            return
        say("--- debugnan %d at %d %d" % (event, x, y))
        self.walk_trace(trace, rd.ShaderStage.Pixel, limit)

    def postvs(self, event, limit=8):
        """Print the vertices with NaN outputs at this draw. Debug the vertex shader of the first one."""
        self.controller.SetFrameEvent(event, True)
        action = next(item for item in walk(self.controller.GetRootActions()) if item.eventId == event)
        mesh = self.controller.GetPostVSData(0, 0, rd.MeshDataStage.VSOut)
        stride = mesh.vertexByteStride
        data = self.controller.GetBufferData(mesh.vertexResourceId, mesh.vertexByteOffset, 0)
        count = len(data) // stride
        say("--- postvs %d: indices %d, stored vertices %d, stride %d" % (event, mesh.numIndices, count, stride))
        pipe = self.controller.GetPipelineState()
        for signature in pipe.GetShaderReflection(rd.ShaderStage.Vertex).outputSignature:
            say("  output %s reg %d comps %d" % (signature.varName, signature.regIndex, signature.compCount))
        bad = {}
        for vertex in range(count):
            floats = struct.unpack_from("<%df" % (stride // 4), data, vertex * stride)
            odd = [slot * 4 for slot, value in enumerate(floats) if value != value or abs(value) == float("inf")]
            if odd:
                bad[vertex] = odd
        say("  vertices with NaN or Inf: %d" % len(bad))
        for vertex in sorted(bad)[:limit]:
            say("    vertex %d byte offsets %s" % (vertex, bad[vertex]))
        if not bad:
            return
        mesh_indices = range(mesh.numIndices)
        if mesh.indexResourceId != rd.ResourceId.Null():
            mesh_indices = struct.unpack("<%d%s" % (mesh.numIndices, {1: "B", 2: "H", 4: "I"}[mesh.indexByteStride]),
                                         self.controller.GetBufferData(mesh.indexResourceId, mesh.indexByteOffset,
                                                                       mesh.numIndices * mesh.indexByteStride))
        position = next(index for index, vertex in enumerate(mesh_indices) if vertex in bad)
        buffer = pipe.GetIBuffer()
        width = buffer.byteStride
        raw = self.controller.GetBufferData(buffer.resourceId, buffer.byteOffset + (action.indexOffset + position) * width, width)
        index = int.from_bytes(raw, "little")
        say("  first bad index position %d, index %d, base vertex %d" % (position, index, action.baseVertex))
        trace = self.controller.DebugVertex(index + action.baseVertex, 0, index, 0)
        if trace.debugger is None:
            say("  no debugger for this vertex")
            return
        self.walk_trace(trace, rd.ShaderStage.Vertex, limit)

    def vinputs(self, event, first=0, count=40):
        """Print the vertex layout of this draw and the raw vertex data."""
        self.controller.SetFrameEvent(event, True)
        pipe = self.controller.GetPipelineState()
        buffers = pipe.GetVBuffers()
        inputs = pipe.GetVertexInputs()
        action = next(item for item in walk(self.controller.GetRootActions()) if item.eventId == event)
        say("--- vinputs %d: base vertex %d, index offset %d" % (event, action.baseVertex, action.indexOffset))
        for index, buffer in enumerate(buffers):
            if rid_number(buffer.resourceId):
                say("  buffer %d: %d (%s) offset %d stride %d" % (index, rid_number(buffer.resourceId),
                                                                 self.names.get(rid_number(buffer.resourceId), "?"),
                                                                 buffer.byteOffset, buffer.byteStride))
        for attribute in inputs:
            if attribute.used:
                say("  input %s: buffer %d offset %d format %s" % (attribute.name, attribute.vertexBuffer,
                                                                   attribute.byteOffset, attribute.format.Name()))
        for vertex in range(first, first + count):
            parts = []
            for attribute in inputs:
                if not attribute.used:
                    continue
                buffer = buffers[attribute.vertexBuffer]
                start = buffer.byteOffset + (vertex + action.baseVertex) * buffer.byteStride + attribute.byteOffset
                raw = self.controller.GetBufferData(buffer.resourceId, start, attribute.format.ElementSize())
                text = raw.hex()
                if "32G32B32" in attribute.format.Name() and attribute.format.compType == rd.CompType.Float:
                    text = "%.4g %.4g %.4g" % struct.unpack_from("<3f", raw)
                parts.append("%s=%s" % (attribute.name, text))
            say("  v%d %s" % (vertex, " ".join(parts)))

    def bufwatch(self, number, offset, size, stride=64):
        """Print each use of this buffer that changes the given bytes. Print the first float of each changed record."""
        rid = next(buffer.resourceId for buffer in self.controller.GetBuffers() if rid_number(buffer.resourceId) == number)
        uses = self.controller.GetUsage(rid)
        say("--- bufwatch %d offset %d size %d: %d uses" % (number, offset, size, len(uses)))
        self.controller.SetFrameEvent(1, True)
        last = self.controller.GetBufferData(rid, offset, size)
        say("  at the start, x of each record: %s" % ["%.4g" % value for value in struct.unpack_from(
            "<%df" % (size // 4), last)][:: stride // 4][:40])
        seen = set()
        for use in uses:
            if use.eventId in seen:
                continue
            seen.add(use.eventId)
            kind = str(use.usage).split(".")[-1]
            if kind in ("VB", "IB", "VS_Constants", "PS_Constants", "CS_Constants", "CS_Resource", "VS_Resource",
                        "PS_Resource", "CopySrc", "Barrier", "Indirect", "Constants"):
                continue
            self.controller.SetFrameEvent(use.eventId, True)
            now = self.controller.GetBufferData(rid, offset, size)
            if now != last:
                changed = [index // stride for index in range(0, size, stride) if now[index:index + stride] != last[index:index + stride]]
                say("  %d %s changed records %d..%d (%d)" % (use.eventId, kind, changed[0], changed[-1], len(changed)))
                last = now
        say("  uses checked %d" % len(seen))

    def walk_trace(self, trace, stage, limit):
        pipe = self.controller.GetPipelineState()
        pipeline = pipe.GetGraphicsPipelineObject()
        text = self.controller.DisassembleShader(pipeline, pipe.GetShaderReflection(stage),
                                                 self.controller.GetDisassemblyTargets(True)[0]).splitlines()
        lines = {info.instruction: info.lineInfo.disassemblyLine for info in trace.instInfo}
        known = {}
        found = 0
        steps = 0

        def values(var):
            if len(var.members) > 0:
                result = []
                for member in var.members:
                    result += values(member)
                return result
            if var.type == rd.VarType.Float:
                return list(var.value.f32v)[:var.rows * var.columns]
            return list(var.value.u32v)[:var.rows * var.columns]

        while found < limit:
            states = self.controller.ContinueDebug(trace.debugger)
            if not states:
                break
            for state in states:
                steps += 1
                for change in state.changes:
                    var = change.after
                    if not var.name:
                        continue
                    now = values(var)
                    known[var.name] = now
                    odd = var.type == rd.VarType.Float and any(v != v or abs(v) == float("inf") for v in now)
                    if not odd or found >= limit:
                        continue
                    found += 1
                    number = lines.get(state.nextInstruction, 0)
                    line = text[number - 1].strip() if 0 < number <= len(text) else "?"
                    say("  step %d line %d %s = %s" % (steps, number, var.name, now))
                    say("    %s" % line)
                    for word in sorted(set(line.replace("(", " ").replace(")", " ").replace(",", " ").split())):
                        if word.startswith("_") and word in known and word != var.name:
                            say("    %s = %s" % (word, known[word]))
        say("  steps %d, odd values %d" % (steps, found))
        path = os.path.join(OUT, "trace-%s.txt" % str(stage).split(".")[-1])
        with open(path, "w") as out:
            out.write("\n".join(text) + "\n\n=== values\n")
            for name in sorted(known):
                out.write("%s = %s\n" % (name, known[name]))
        say("  wrote %s" % path)
        self.controller.FreeTrace(trace)

    def copies(self, first, last):
        """Print the source and the destination of each copy in this event range."""
        say("--- copies %d to %d" % (first, last))
        for action in walk(self.controller.GetRootActions()):
            if first <= action.eventId <= last and action.flags & (rd.ActionFlags.Copy | rd.ActionFlags.Resolve):
                say("  %d %s -> %s" % (action.eventId, self.texture_text(rid_number(action.copySource)),
                                       self.texture_text(rid_number(action.copyDestination))))

    def save_texture(self, event, number, mip=0):
        save = rd.TextureSave()
        save.resourceId = self.textures[number].resourceId
        save.mip = mip
        save.slice.sliceIndex = 0
        save.alpha = rd.AlphaMapping.Discard
        save.destType = rd.FileType.PNG
        path = os.path.join(OUT, "ev%06d-res%d-mip%d.png" % (event, number, mip))
        result = self.controller.SaveTexture(save, path)
        say("saved %s: %s (%s)" % (path, result, self.texture_text(number)))

    def mips(self, event, number):
        """Save each mip of this resource at this event."""
        self.controller.SetFrameEvent(event, True)
        for mip in range(self.textures[number].mips):
            self.save_texture(event, number, mip)

    def save(self, event, number=None):
        self.controller.SetFrameEvent(event, True)
        if number is not None:
            self.save_texture(event, number)
            return
        for target in self.controller.GetPipelineState().GetOutputTargets():
            if rid_number(target.resource):
                self.save_texture(event, rid_number(target.resource))

    def history(self, number, x, y):
        tex = self.textures[number]
        sub = rd.Subresource(0, 0, 0)
        say("--- history of %s at %d %d" % (self.texture_text(number), x, y))
        events = list(walk(self.controller.GetRootActions()))
        self.controller.SetFrameEvent(events[-1].eventId, True)
        for mod in self.controller.PixelHistory(tex.resourceId, x, y, sub, rd.CompType.Typeless):
            after = mod.postMod.col.floatValue
            say("  %d passed %s shader out %s after %s" % (mod.eventId, mod.Passed(),
                                                           list(mod.shaderOut.col.floatValue)[:4], list(after)[:4]))


def run():
    capture = rd.OpenCaptureFile()
    result = capture.OpenFile(os.environ["RDOC_CAP"], "", None)
    say("open file: %s" % result)
    say("local replay: %s, api %s" % (capture.LocalReplaySupport(), capture.DriverName()))
    result, controller = capture.OpenCapture(rd.ReplayOptions(), None)
    say("open capture: %s" % result)
    session = Session(controller)
    for line in os.environ["RDOC_COMMANDS"].replace("|", "\n").splitlines():
        words = line.split()
        if not words:
            continue
        say("> " + line)
        try:
            getattr(session, words[0])(*[int(word) for word in words[1:]])
        except Exception:
            say(traceback.format_exc())
    controller.Shutdown()
    capture.Shutdown()


try:
    run()
except Exception:
    say(traceback.format_exc())
say("done")
report.close()
os._exit(0)
