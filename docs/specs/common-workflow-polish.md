# Common workflow polish

## Metadata

- slug: common-workflow-polish
- status: approved
- owner: PM/Architect/Engineer
- related_roadmap: docs/roadmap.md#future-candidates
- related_docs:
  - docs/gap-analysis.md
- related_specs:
  - docs/specs/cli-safety-and-diagnostics.md
  - docs/specs/custom-proxy-command.md
  - docs/specs/jump-host-connection-modes.md

## Background

sshgo is a personal tool, so the best return comes from polishing the paths used most often:

- browsing host details before connecting
- adding or editing a host in the TUI
- uploading or downloading a file

The project should avoid broad, low-frequency feature expansion unless repeated personal usage justifies it. This change focuses on early feedback and clearer state for existing workflows.

## Scope

- Validate TUI add/edit candidate nodes before writing `hosts.json`.
- Keep validation messages user-facing and concise.
- Make the detail pane show resolved connection state instead of mostly raw fields.
- Reject clearly unsafe SFTP paths before Expect handoff.
- Preserve current stdlib-only and Expect handoff constraints.

## Non-goals

- Do not implement directory transfer.
- Do not replace the TUI form system.
- Do not add tags, favorites, batch operations, or health checks.
- Do not change relay path quoting behavior.
- Do not add external dependencies.

## Acceptance Criteria

1. TUI add flow validates the candidate host/group in the current config context before saving.
2. TUI edit flow validates the candidate host/group in the current config context before saving.
3. Invalid TUI values such as bad ports, missing auth, invalid placeholders, unsupported deep nesting, or invalid proxy fields are shown before writing config.
4. The detail pane shows resolved target, auth method, SSH jump mode, transfer mode, host key mode, parent jump host, and proxy command where relevant.
5. Detail rendering must not expose saved passwords or MFA secrets.
6. Direct/tunnel SFTP paths containing newline, carriage return, double quote, or backslash fail before Expect handoff with a clear error.
7. Relay transfers keep their existing path handling.
8. README, docs index, roadmap, and gap analysis are updated.

## Technical Design

### TUI Candidate Validation

`HostManager` should expose validation helpers that build an in-memory candidate config and call existing `validate_hosts_config()`:

- add candidate: insert the new node into a cleaned copy of the current tree
- update candidate: replace the existing node in a cleaned copy of the current tree

No validation helper should write files, assign permanent IDs, encrypt secrets, or mutate the active tree.

The TUI should call these helpers after form data is normalized but before `add_node()` or `update_node()`. Errors are displayed in the TUI and the save operation is cancelled.

### Detail Pane

`HostManager` should expose a small read-only host description helper for TUI display. It should resolve placeholders defensively and return display pairs. The TUI remains responsible for wrapping and drawing.

### SFTP Path Guard

SFTP command mode sends `put/get` commands to the interactive `sftp>` prompt. The current string protocol is fragile for some characters. Until a fuller SFTP escaping model exists, direct/tunnel SFTP should reject paths containing:

```text
\n
\r
"
\
```

Relay mode is not changed because it already uses shell-quoting in `relay_transfer.exp`.

## Review Status

- status: reviewed
- verdict: PASS
- notes: The scope improves existing high-frequency workflows without adding broad feature surface.
