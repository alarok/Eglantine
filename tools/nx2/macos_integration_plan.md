# Integrating the macOS work from the forks

Three trees carry macOS and NX2 work that our `nx2` does not have. This note records how they
relate, what blocks a merge today, and the order to do it in.

## The trees

| Tree | What it adds |
|---|---|
| `zortos293/Eglantine` (`nx2`) | One 63-file commit: sparse image backing, partial texture writes, pipeline workers, a dynarmic block-range rewrite, readback coherence. Plus a perf commit (page bitmap batching, reset-program cache, mixed-ASID fix). |
| Pull request 241 in `Djihads80/Eglantine` (`cblock85`, "Mac") | 50 files. macOS sparse render-target guard, MoltenVK/KosmicKrisp pipeline cache rejection, driver quirks, settings notes. Built on the zortos tree. |
| `upstream/nx2` | 43 commits we lack: `ISBERD 0x923`, a `dma_pusher` fast path, sparse image work. |

## What blocks it today

- Cherry-picking the 63-file commit onto our `nx2` leaves **18 conflicted files**; merging the
  whole zortos branch leaves **47**. Our tree has its own NX2 work in the same files
  (`dma_pusher`, `macro`, `gpu`, `scheduler`, `texture_cache`, tests/CMakeLists).
- The trees are structurally different, not just textually: our `block_range_information` uses
  `boost::icl::interval_map` and theirs a `multimap`; our test list in `src/tests/CMakeLists.txt`
  no longer matches theirs, so neither side's list can be taken whole.
- Upstream adds `dist/eglantine.icns` while the tree has `dist/Eglantine.icns`, which collide on
  case-insensitive APFS and break checkout. Keep one and update references.

## Order

1. Work on a case-sensitive APFS volume. `hdiutil create -fs APFSX` failed on macOS 27.2, so use a
   normal volume and resolve the icon by deleting `dist/Eglantine.icns`.
2. Merge zortos with `--no-ff`, one file per decision, never wholesale ours or theirs.
   Rule: NX2 GPU files keep our guarantees and take their additions; sparse/texture/pipeline files
   follow zortos, because the feature is theirs; dynarmic takes one complete representation and
   ports every operation, never a mix.
3. Merge pull request 241 on top, which then applies to a tree that has its sparse flags.
4. Merge upstream last, porting `ISBERD 0x923` and the `dma_pusher` fast path by hand.
5. Build with `compile-check`, then a macOS dmg, then verify on the Mac: menus, a race, and the
   sparse render targets that turn pink today.

## What is already ours

The macOS fixes from this session are in `nx2`: lazy RomFS for loose dumps, no `format=0` assert on
MoltenVK, texture budget from the host memory, the pipeline cache rejection (pull request 24), the
SDL3 title update on the main thread, and the configuration dialog sizing.
