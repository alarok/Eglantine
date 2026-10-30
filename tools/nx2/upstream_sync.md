# Upstream sync

The `Sync upstream` workflow checks `Djihads80/Eglantine` `nx2` every day.
You can also start it from the Actions page.

The workflow merges upstream changes into a reserved branch named
`automation/sync-upstream-nx2`. It merges the current fork `nx2` first.
It does not rewrite branch history. A conflict stops the run before a push.

One pull request tracks the updates. The required check validates workflow
files and the CI classifier. It builds Windows and Linux when changes affect
emulator code, builds, dependencies, or unknown paths. The builds do not run
project tests or verify game behavior.
The workflow enables automatic merge after required validation passes.

Add an active `nx2` ruleset before using automatic merge. Require pull
requests, current checks, no force pushes, and no branch deletion. Add no
bypass actors. Allow merge commits:

- `linux-x86_64 binary`
- `windows-x86_64 binary`

The workflow checks the active rules for `Required validation` and strict mode.
Enable auto-merge in the repository settings. Enable Actions to create pull
requests. The workflow uses the repository `GITHUB_TOKEN`; it needs no PAT.

Pushes and merges made with a user token start the existing release workflow.
That workflow publishes a prerelease after both platform builds pass.
The sync uses `GITHUB_TOKEN`, which does not start another workflow after its merge.
The sync dispatches its own Windows and Linux builds with publication disabled.
Start a release manually when needed.

If a merge conflict occurs, read the failed sync run and resolve the conflict
on a local branch. Do not edit the reserved bot branch. Open a pull request
for the resolved changes. Close the sync pull request to pause future runs.
Reopen it to resume automatic updates.
