# macOS arm64 fastmem

The Mac build runs without fastmem. Every guest memory access goes through the page table, so the
guest runs on dynarmic instead of NCE, and the frames cost two to six times what they cost on the
same code on Windows or SteamOS. Issue 16 holds the log lines and the measurements.

This note records what the code does today, why it cannot work on a 16 KB host page, the design a
fix needs, and one trap that a first design got wrong.

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
  granularity, and `mprotect` rounds up to the host page.

`src/core/device_memory.cpp` reserves 1<<38 bytes (256 GiB) of virtual space when NCE is available
and 1<<39 otherwise.

## Why the arena must be complete

There is no SIGSEGV handler for a guest access in the fastmem path. A hole inside the arena is a
crash, not a slow access.

## What a first design got wrong

Marking a granule "slow" in the page table does not help. A fastmem access is compiled as
`arena_base + guest_address`; it never reads the page table again. Removing the pointer for a page
takes effect at the next compilation, not at the next access, and any compiled access that still
points into an unmapped granule faults.

So a mixed granule must be **unmapped in the arena** (`PROT_NONE` or a hole), which produces the
fault that makes the runtime recompile that access through the page table. Two consequences:

- The degradation is per access site, not per address: one mixed page can slow every load and store
  that was compiled against it until the block is invalidated.
- The revocation has to be synchronised with the executors, in the same way the code cache handles
  invalidation today.

## What a fix needs

1. **Host page size at runtime.** Read `sysconf(_SC_PAGESIZE)` once, keep it as `HostPageSize`, and
   keep `PageAlignment` (4 KB) as the guest page. Drop the assert and use `HostPageSize` for every
   arena offset, length, and protection call.
2. **Reserve an arena without a hint.** Either `mach_vm_allocate` with a fixed address taken from a
   probe, or `mmap(nullptr, ...)` and accept the address that comes back.
3. **Map in host granules.** A guest mapping is contiguous in the guest address space, one host
   offset, one permission set. Map it only when the range starts and ends on a host page boundary
   and the host offset is congruent modulo the host page. Otherwise leave the granule unmapped.
4. **Leave mixed granules out of the arena**, as described above, and let the fault path recompile
   the access through the page table.
5. **Protection.** A permission change on part of a granule cannot be expressed. Unmap the granule
   and let the fault path handle it.
6. **Do not promise the whole win.** Enable only the stable, compatible regions first, and measure
   how much of the guest address space they cover and how often the fault path runs. Expect the
   guest executable pages to be fine: dynarmic does not need `PROT_EXEC` on them. `separate_heap`
   is Android only in this tree.

## The main risk

GPU memory tracking. The rasterizer protects and unprotects 4 KB guest ranges while it downloads
or uploads images, and with a 16 KB granule each of those calls also touches its three neighbours.
It may also need coherence between aliases of the same host memory. That is the place where a fix
turns into frequent degradation rather than a win. This is a prediction; measure it first.

## NCE afterwards

NCE is a separate project, not a switch. An arbitrary arena does not place memory at guest
addresses, and Darwin adds its own context and exception handling, TLS, SVC, and the x18 register
that Apple reserves. `PROT_EXEC` working for a non-hardened app does not answer those contracts.

## Validation

Measure the same scenes before and after, on the same Mac, with the same settings:

- Mario Kart World 1.8.0, which today reports 25 FPS with the 16/32 GiB texture budget and the same
  frame at 0.5x, so the cost is not pixel-dependent.
- Pokémon Pokopia in the field, 53 to 60 FPS today.
- Donkey Kong Bananza at its mode select, 60 FPS today.

Count the fault-path entries per frame at the same time: a build that is fast only because it
faults on every access has not fixed anything.
