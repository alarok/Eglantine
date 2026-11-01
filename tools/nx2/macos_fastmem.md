# macOS arm64 fastmem

The Mac build runs without fastmem. Every guest memory access goes through the slow path, so the
guest runs on dynarmic instead of NCE, and the frames cost two to six times what they cost on the
same code on Windows or SteamOS. Issue 16 holds the log lines and the measurements.

This note records what the code does today, why it cannot work on a 16 KB host page, and the shape
of a fix.

## Today

`src/common/host_memory.cpp`:

- `PageAlignment` is `0x1000` and `HugePageSize` is `0x200000` (`:76` and `:77`).
- `Impl::Init` asserts that `sysconf(_SC_PAGESIZE)` is `0x1000` (`:523`). Apple Silicon uses 16 KB
  pages, so the assert fires on every boot and the code continues with a 4 KB assumption.
- `ChooseVirtualBase` for `ARCHITECTURE_arm64` (`:416`) tries up to 64 random addresses and accepts
  a mapping only when `mmap` returns exactly the requested address. macOS does not honour the hint,
  so every attempt is rejected and the function returns `MAP_FAILED`.
- `HostMemory` sees the failure, sets `fallback_buffer`, allocates a plain buffer, leaves
  `virtual_base` null, and logs `Platform can support fastmem, but can't create it` (`:730`).
- `Impl::Map` (`:594`) calls `mmap(MAP_FIXED)` with a 4 KB aligned offset and length. On a 16 KB
  host page that call fails with `EINVAL`. `Impl::Protect` (`:629`) calls `mprotect` with the same
  4 KB granularity, and `mprotect` rounds up to the host page, so it would apply to its neighbours.

`src/core/device_memory.cpp` reserves 1<<38 bytes (256 GiB) of virtual space when NCE is available
and 1<<39 otherwise.

There is no SIGSEGV handler for a guest access in the fallback path; a hole inside the arena is a
crash, not a slow access. The arena must therefore be complete before the page table publishes a
pointer into it.

## What a fix needs

1. **Host page size at runtime.** Read `sysconf(_SC_PAGESIZE)` once, keep it as `HostPageSize`, and
   keep `PageAlignment` (4 KB) as the guest page. Drop the assert and use `HostPageSize` for every
   arena offset, length, and protection call.
2. **Reserve an arena without a hint.** Either `mach_vm_allocate` with a fixed address taken from a
   probe, or `mmap(nullptr, ...)` and accept the address that comes back. Do not compare it with a
   hint. Record it as `virtual_base`.
3. **Map in host granules.** A guest mapping is a contiguous range in the guest address space with
   one host offset and one permission set. Four guest pages share one 16 KB host page. When the
   range starts and ends on a host page boundary, map it directly with `MAP_FIXED`. When it does
   not, the shared granule holds two different mappings and cannot be expressed; mark that granule
   as slow.
4. **Publish pointers only for complete granules.** `DeviceMemoryManager::Map` publishes a fastmem
   pointer and then calls `HostMemory::Map`. Invert that: ask whether the range maps, and only
   publish the pointer when it does. Pages in a slow granule keep no pointer, so the JIT takes its
   slow path for them. This is the part that must not be skipped: without it the first slow granule
   is a SIGSEGV.
5. **Protection.** A permission change on part of a granule cannot be expressed either. Treat it as
   a slow granule: keep the mapping with the union of the permissions, and stop publishing pointers
   for the guest pages inside it.
6. **Unmap.** Freeing part of a granule leaves the rest mapped or not, depending on the neighbours.
   Mark the granule slow and let the placeholders handle the rest.

## Validation

Measure the same scenes before and after, on the same Mac, with the same settings:

- Mario Kart World 1.8.0 at the world map, which today reports 5 to 26 FPS (issue 19).
- Pokémon Pokopia in the field, which today reports 53 to 60 FPS, 17.7 ms while walking.
- Donkey Kong Bananza at its mode select, 60 FPS today, so a regression shows at once.

A `sample` of the process is the quick check: with fastmem the samples move from the dynarmic JIT
to the NCE code. Keep the before numbers in the pull request.

## Limits

This is an architecture change to the memory path. It touches the page table that NCE also uses, so
a mistake is a crash on every platform, not only on the Mac. Change it on a branch, test on a
16 KB host, and do not merge it without the three scenes above.
