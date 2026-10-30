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
- The secondary configuration directory is `C:/Users/Usuario/AppData/Roaming/GitHub CLI-alarok-eglantine`.
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
Do not infer account identity from old notes or a missing-folder claim.
Compare the host, wrapper path, and live API result when agents report different accounts.
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
Use the `Sync upstream` workflow for scheduled updates.
It merges fork and upstream histories on `automation/sync-upstream-nx2`.
A conflict stops the workflow before it changes remote branches or PRs.
The bot dispatches full Windows and Linux builds before automatic integration.
Keep the `Required validation` check mandatory and require current checks on `nx2`.

Documentation and CI-only PRs run workflow lint and CI behavior tests.
Emulator, build, dependency, and unknown changes require both platform builds.
Skipped platform builds must remain visible as skipped checks.
Manual build dispatches and pushes run both platform builds.
Build success does not prove game compatibility or increased FPS.
See `tools/nx2/upstream_sync.md` for workflow behavior and release triggers.

## Runtime evidence

Use isolated portable profiles for game tests.
Keep original saves, keys, firmware, and shader caches intact.
Run one heavy emulator at a time. Stop only processes owned by the current test.
Reuse capture, replay, and diagnostic tools before repeating slow game runs.
Compare the same scene and settings before claiming a performance gain.
Preserve draw coverage and report rejected work, crashes, and visual regressions.
Inspect native presented frames before claiming a visual fix.
An API acknowledgement proves host input application, not a game's response.
Do not add success stubs for unknown guest commands without a verified contract.
Keep games, keys, firmware, saves, caches, dumps, and large logs outside Git.
Use relevant viewport screenshots when they show the changed behavior.

## Upstream text correction

Upstream `build-55` targets `d26ed5de848d963ef62165cc3c387c48f35825e0`.
It includes `a4a746b47b`, which accepts R0 shader returns for Mario Kart World text.
Do not create a duplicate fix for that change.
Compare a clean upstream GUI build before attributing another rendering fault to this fork.
The isolated candidate still has captures with missing labels; do not report complete text validation from the upstream commit alone.
Release: https://github.com/Djihads80/Eglantine/releases/tag/build-55
