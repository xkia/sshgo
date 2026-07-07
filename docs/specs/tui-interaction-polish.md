# TUI Interaction Polish

## Metadata

- slug: tui-interaction-polish
- status: reviewed
- owner: PM/Architect/Engineer
- related_roadmap: docs/roadmap.md#2026-07
- replaces: completed TUI style, form interaction, and input editing specs

## Purpose

This spec records the accepted TUI interaction and implementation boundaries after the completed style, form, and input-editing polish work. It keeps the daily host browsing/add/edit/delete behavior in one current document and removes completed intermediate planning docs.

## Accepted Behavior

- The main list, forms, messages, and detail pane share one visual shell and footer style.
- The selection page does not use an unnecessary outer frame.
- The detail pane uses a side-by-side split layout when width allows and does not overwrite list rows.
- The Recent tab row is hidden when Recent is disabled or empty.
- Existing keyboard shortcuts remain unchanged.
- Add/Edit host forms are grouped into Basic, Auth, and Advanced sections.
- Advanced fields are collapsed by default for new hosts and opened when editing a host that already uses advanced fields.
- Save-time validation stays inside the form, preserves typed values, and focuses a likely field when one can be inferred.
- Delete confirmation defaults to Cancel and summarizes the target host or group descendant impact.
- Text and password fields support cursor movement, Home/End, Ctrl+A/Ctrl+E, Backspace, Delete, Ctrl+U, paste-friendly printable insertion, Enter commit, and Esc cancel.
- Password fields use the same editing behavior as text fields while masking display text.

## Implementation Boundaries

- `Tui` owns curses screen lifecycle, windows, navigation state, form loops, and high-level user flows.
- `tui_text.py` owns pure key/text editing helpers and ellipsizing.
- `tui_forms.py` owns pure form schema construction, dynamic field visibility, clean form data, and form-to-node/update conversion.
- Do not introduce external dependencies or a GUI/web UI.
- Do not split `Tui` into several stateful classes unless a future change has a concrete coordination or testability problem that justifies the state-passing cost.
- Do not change SSH/SFTP/relay execution behavior from TUI polish work.

## Test Boundaries

- `tests/test_tui.py` covers curses-facing rendering, navigation, Recent, add/edit/delete, and fake-screen flows.
- `tests/test_tui_text.py` covers pure text editing behavior.
- `tests/test_tui_forms.py` covers form schemas, auth/advanced visibility, form conversion, and default jump-mode persistence behavior.

## Non-goals

- Do not add mouse support.
- Do not add new host-management features.
- Do not replace curses.
- Do not change validation, save semantics, field trimming, config schema, or connection handoff behavior.

## Verification

Use the broad verification commands in `AGENTS.md`. For narrow TUI-only changes,
the minimum focused coverage should include `tests.test_tui`,
`tests.test_tui_text`, and `tests.test_tui_forms`.

## Review Status

- status: reviewed
- verdict: PASS
- notes: Consolidated from completed TUI style, form interaction, and input editing specs. Current guidance is to avoid further TUI splitting unless a concrete future change needs it.
