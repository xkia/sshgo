# Final risk hardening

## Metadata

- slug: final-risk-hardening
- status: approved
- owner: Architect/Engineer
- related_roadmap: docs/roadmap.md#2026-07
- related_docs:
  - docs/gap-analysis.md
- related_specs:
  - docs/specs/internal-refactors-and-tests.md
  - docs/specs/tui-interaction-polish.md
  - docs/specs/node-identity-recent-hardening.md

## Background

Final independent review found two remaining risks in the current optimization
slice:

- The config lock prevents corrupt partial files, but it does not stop a stale
  `HostManager` instance from overwriting another instance's already-saved edit.
- TUI add-parent selection can include generated or read-only runtime nodes such
  as Recent and imported `~/.ssh/config` entries, which can make an add operation
  appear successful without persisting where the user expected.

Both risks affect trust in common personal-tool workflows. The fix should remain
small and dependency-free.

## Scope

- Add stale-write detection for `ConfigStore.write_json()` callers that provide
  the fingerprint of the config version they loaded.
- Make `HostManager` remember the loaded config fingerprint and reject saves if
  the active file changed since that load.
- Keep file locking as corruption prevention; stale-write detection is a
  user-facing conflict guard, not an automatic merge system.
- Filter TUI add-parent selection to `[Top Level]` plus saved, editable host/group
  nodes.
- Reject generated/read-only preselected parents defensively.
- Add focused tests for stale-write rejection and add-parent filtering.

## Non-goals

- Do not implement automatic config merge or multi-writer collaboration.
- Do not add a database, journal, or external dependency.
- Do not change JSONC parsing or config format.
- Do not change Recent rendering in normal browse mode.
- Do not change edit/delete read-only handling beyond parent selection.

## Acceptance Criteria

1. A `HostManager` save fails instead of overwriting when the active config file
   changed after that manager loaded it.
2. Successful saves update the manager's remembered file fingerprint so repeated
   edits from the same instance continue to work.
3. Existing lock-backed writes without an expected fingerprint keep working for
   direct `ConfigStore` usage.
4. TUI parent selection shows only `[Top Level]` plus saved editable nodes.
5. TUI add flow refuses generated/read-only preselected parents.
6. Tests cover stale-write rejection and filtered parent selection.
7. Existing full unittest, compile, validate, and diff checks pass.

## Technical Design

Use a small file fingerprint tuple based on `os.stat()` values that are stable
enough to detect ordinary external writes: inode, size, nanosecond mtime, and
nanosecond ctime when available. `ConfigStore.write_json()` accepts an optional
`expected_fingerprint`. It checks the active file while holding the same config
lock used for backup rotation and `os.replace()`. If the fingerprint does not
match, it raises a dedicated conflict exception before backups or replacement.

`HostManager` stores the fingerprint after `_read_config_file()` and passes it to
`write_json()`. A successful write updates that stored fingerprint.

For the TUI, derive parent-select lines from saved hosts only and skip nodes whose
`source` is generated/read-only. Normal navigation can still show Recent and
imported runtime nodes.

## Review Status

- status: reviewed
- verdict: PASS
- notes: Independent review confirmed stale-write detection and editable-only parent selection. Residual risk is limited to metadata-based fingerprinting and unsaved in-memory changes after a detected conflict.
