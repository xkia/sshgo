# TUI form interaction polish

## Metadata

- slug: tui-form-interaction-polish
- status: approved
- owner: PM/Architect/Engineer
- related_roadmap: docs/roadmap.md#2026-07
- related_docs:
  - docs/gap-analysis.md
- related_specs:
  - docs/specs/tui-style-system.md
  - docs/specs/common-workflow-polish.md

## Background

After the shared TUI style system, the add/edit/delete flows still need interaction polish. These are high-frequency personal-tool workflows, so the interface should reduce steps and prevent mistakes without adding new backend features.

## Scope

- Group add/edit host fields into Basic, Auth, and Advanced sections.
- Keep Advanced collapsed by default for new hosts, but expand it when editing a host that already uses advanced fields.
- Keep validation failures inside the form, preserve typed values, and focus the likely field causing the error.
- Improve delete confirmation so Cancel is the default focus and the page summarizes what will be deleted.
- Preserve existing keyboard behavior, stdlib-only curses implementation, and connection/config semantics.

## Non-goals

- Do not add a GUI or external dependency.
- Do not change SSH/SFTP/relay execution behavior.
- Do not implement CommandPlan extraction in this spec.
- Do not require typing the node name to delete.
- Do not add new auth backends.

## Acceptance Criteria

1. Add/Edit host forms show Basic, Auth, and Advanced sections.
2. Advanced fields are hidden until the Advanced toggle is opened.
3. Editing a host with `proxy_command`, `ssh_jump_mode`, or `transfer_jump_mode` opens Advanced by default.
4. Save-time validation errors stay on the form and keep the user's current input.
5. Save-time validation moves focus to a likely field when one can be inferred.
6. Delete confirmation defaults focus to Cancel.
7. Delete confirmation summarizes host target or group descendant count.
8. Existing tests pass and new tests cover advanced visibility, in-form validation, and delete default focus.

## Technical Design

Keep rendering inside `tui.py`. Add small helpers for:

- host form field construction
- group form field construction
- add/update validator callbacks
- validation error-to-field focus inference
- delete impact text

The form loop should support `section` and `toggle` field types in addition to the existing text, password, radio, static text, and button controls. Advanced fields can remain ordinary semantic fields marked with `advanced: True`; the form loop controls their visibility from the Advanced toggle state.

## Review Status

- status: reviewed
- verdict: PASS
- notes: The change improves frequent TUI workflows while keeping backend behavior unchanged.
