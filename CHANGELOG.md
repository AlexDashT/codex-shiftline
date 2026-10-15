# Changelog

## 1.1.0 — interactive session selection

- `shiftline switch <profile>` now opens the native Codex conversation picker instead of immediately resuming the most recent session.
- Added `--all` for cross-directory sessions and `--last` to opt into the former behavior.
- Preserved profile and daemon-lock safety, with expanded tests.

## 1.0.0 — initial standalone release

- Rebranded the independently maintained cxswap-inspired profile runner as **Codex Shiftline**.
- Kept existing standalone `~/.codex-profiles-lite` profiles usable without reauthentication.
- Isolated authentication and daemon directories while sharing sessions and project state.
- Safe one-command `switch` with optional managed-daemon stop, dry run, and Codex flag passthrough.
- Added GitHub-ready documentation, tests, security notices and CI.

Previous work was distributed as `cxswap-standalone` versions 1.0.0–1.0.4, not as part of this repository's release history.