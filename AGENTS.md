# Agent instructions for the Alarok fork

## Owner instructions

Follow Deku's current task instructions before inherited upstream policies.
Read `docs/policies/AI.md` and `docs/policies/Coding.md` for the remaining project rules.
Use English for new code comments, documentation, commit messages, and pull request text.
Use short, active sentences and consistent technical terms.
Reply to Deku in clear Spanish from Spain.

## Repository and accounts

- The development fork is `https://github.com/alarok/Eglantine`.
- `origin` selects that fork. `upstream` selects `https://github.com/Djihads80/Eglantine`.
- Keep pushes disabled for `upstream` and reference forks.
- The default branch is `nx2`.
- The primary checkout is `C:/Users/Usuario/DEV/Eglantine`.
- The candidate build worktree is `C:/egl-mkw`.
- Use `gh-alarok` for this fork. Use `gh-deku` for the primary account.
- The wrappers are in `C:/Users/Usuario/.local/bin`.
- Both wrappers use the portable GitHub CLI at `C:/Users/Usuario/Tools/GitHubCLI/2.103.3/bin/gh.exe`.
- The secondary configuration directory is `C:/Users/Usuario/.config/gh-alarok`.
- The Eglantine Git credential helper uses that same shared directory.
- Keep shared configuration outside `AppData`.
- Codex's MSIX environment can redirect `AppData` writes into its package `LocalCache`.
- Other programs can see a different directory at the same apparent `AppData` path.
- Credentials remain in Windows Credential Manager. Do not create global token environment variables.
- Secondary authentication changes restore the primary account's legacy credential.
- The old system `gh` can read that legacy credential. Use the account wrappers.

Check the live account before a remote change:

```powershell
& C:/Users/Usuario/.local/bin/gh-alarok.cmd api user --jq .login
& C:/Users/Usuario/.local/bin/gh-deku.cmd api user --jq .login
```

Expect `alarok` and `deku-95`, respectively.
Cloning with an account does not select the account for later pushes.
Check the repository's Git credential helper separately before a push.
Do not infer account identity from old notes.
Investigate directory visibility when agents report different accounts or missing configuration.
Compare the host, wrapper path, and live API result in each affected program.
Never print tokens or copy credentials into repository files.

## Branches and pull requests

Inspect `git status`, the current branch, and `git worktree list` before editing.
Preserve unrelated changes. Do not switch branches in another agent's active worktree.
Use one `codex/` branch for each independent change.
Keep changes small and keep imported authorship intact.
Use `alarok` and its GitHub noreply address for new fork commits.
Open authorized pull requests in `alarok/Eglantine`, with `nx2` as the base.
Publishing requires authorization for the current task. Authentication alone does not authorize publication.
Do not submit changes to the original project without Deku's explicit request.
Keep emulator behavior changes as drafts until focused checks and review support integration.
Automatic merge is a per-PR option. It is not enabled for all changes.
The sync bot enables it for validated upstream update PRs.
Enable it for another PR only when Deku authorizes integration.
Do not force pushes, reset shared work, or bypass required checks.
Use body files for multiline GitHub text. Disclose AI assistance in commits and PR descriptions.

## Upstream sync and checks

Fetch upstream immediately before comparing changes.
Inspect merged PRs and actual diffs before porting an upstream change.
The `Sync upstream` workflow and the `nx2` ruleset are disabled for now, at Deku's request.
Update `nx2` with GitHub's Sync fork action or a local merge. Direct pushes to `nx2` are allowed.
Platform builds run only from a manual `release-binaries` dispatch.
A cold build takes about 45 minutes. A build with stored objects takes about 15 minutes.
Do not make other work wait for one.
MSVC accepts code that GCC and Clang refuse. Before a push, run `python tools/nx2/clang_check.py <build dir>`.
It checks the changed units with local Clang in seconds. `compile-check` builds each push with GCC and Clang.
Start a release after `compile-check` passes.
Do not push a change to `.github/workflows` while a release runs. `gh release create --target` then gets HTTP 403, because the job token cannot have the `workflows` permission.
If this occurs, download the run artifacts and publish them with `gh-alarok`. Recompile nothing.
Build success does not prove game compatibility or increased FPS.
See `tools/nx2/upstream_sync.md` for workflow behavior and release triggers.

## Windows builds with localized MSVC

Start each script that configures or builds with `chcp 65001 >nul`. Use it for both steps.
MSVC writes its localized `/showIncludes` prefix in the output code page of the console.
CMake writes the same prefix to `rules.ninja` in the code page of the console that configures.
If the bytes differ, Ninja records no headers, and a header change does not rebuild the object.
Agent shells can have different code pages. Never assume that two shells match.
`CMakeModules/MsvcIncludePrefixGuard.cmake` stops such a build before the first compile.
The guard cannot repair old records. To find them, run `ninja -C <build> -t deps` and look for `#deps 0`.
A zero is correct when an object includes only system headers, or when `#ifdef` removes its includes.
Delete the other objects and build again.

## Runtime evidence

Use isolated portable profiles for game tests.
Keep original saves, keys, firmware, and shader caches intact.
Run one heavy emulator at a time. Stop only processes owned by the current test.
Reuse capture, replay, and diagnostic tools before repeating slow game runs.
Use `tools/nx2/debug/` (see its README) to find a silent fault from a log: the draw census, lost shader stores, the command stream capture, and `logdiff.py`.
Compare the same scene and settings before claiming a performance gain.
Preserve draw coverage and report rejected work, crashes, and visual regressions.
Inspect native presented frames before claiming a visual fix.
An API acknowledgement proves host input application, not a game's response.
Mark a success stub for an unknown guest command as a stub in the code and in the log.
Do not copy a real `qt-config.ini` to a test profile. It holds absolute data directories, so the test opens the real saves.
Keep games, keys, firmware, saves, caches, dumps, and large logs outside Git.
Use relevant viewport screenshots when they show the changed behavior.

## Upstream text correction

Upstream `build-55` targets `d26ed5de848d963ef62165cc3c387c48f35825e0`.
It includes `a4a746b47b`, which accepts R0 shader returns for Mario Kart World text.
Do not create a duplicate fix for that change.
Compare a clean upstream GUI build before attributing another rendering fault to this fork.
Mario Kart World shows no text in a session that starts without a game save, on every tested build and setting.
Text appears from the next boot. The cause is still open. Boot twice, or seed a save, before you compare text.
Release: https://github.com/Djihads80/Eglantine/releases/tag/build-55
