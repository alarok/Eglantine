# Claude instructions for the Alarok fork

Read `AGENTS.md` before changing this repository.
That file defines the accounts, branch workflow, publishing scope, checks, and runtime evidence requirements.
Follow Deku's current instructions when inherited upstream guidance conflicts with the authorized task.

Use `C:/Users/Usuario/DEV/Eglantine` as the primary checkout.
Use a separate `codex/` branch for each independent change.
Check active worktrees before editing. Another agent can own `C:/egl-mkw` or a feature worktree.
Do not edit another agent's files or change its active branch.

Use `gh-alarok` for `alarok/Eglantine`.
Verify its identity through `api user` before a remote change.
The primary account remains `deku-95`, selected through `gh-deku`.
The old system `gh` does not reliably select the secondary account.
Check live wrapper results before requesting another login.
Git uses its repository credential helper separately from the GitHub CLI account.
Both secondary paths must select `C:/Users/Usuario/.config/gh-alarok`.
Keep shared configuration outside `AppData`; Codex's MSIX redirection can hide those files from Claude.

Write new technical text and commits in clear English with ASD-STE100 sentence limits.
Use Spanish from Spain when speaking to Deku.
Keep behavior PRs available for review. Automatic upstream sync does not authorize automatic integration of every fix.
Do not claim gameplay, text correctness, or FPS gains from compilation or API acknowledgements.
Record the exact tested boundary and the remaining checks.
