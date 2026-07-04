# TUI input editing polish

## Metadata

- slug: tui-input-editing-polish
- status: approved
- owner: PM/Engineer
- related_roadmap: docs/roadmap.md#2026-07
- related_docs:
  - docs/gap-analysis.md
- related_specs:
  - docs/specs/tui-style-system.md
  - docs/specs/tui-form-interaction-polish.md

## Background

The add/edit forms are now grouped and validated in-place, but text entry still behaves like append-only input. Editing a host, path, username, or proxy command should be comfortable enough for repeated personal use without adding a dependency or replacing curses.

## Scope

- Use one text editor path for text and password fields.
- Support cursor movement with Left/Right.
- Support Home/End and Ctrl+A/Ctrl+E.
- Support Backspace and Delete at the cursor.
- Support Ctrl+U to clear the current field.
- Preserve pasted printable characters, including multi-character input returned by curses.
- Keep Enter as commit and Esc as cancel.

## Non-goals

- Do not add a new forms framework.
- Do not add external dependencies.
- Do not add mouse support.
- Do not change validation, save semantics, field trimming, or config behavior.
- Do not change non-text controls.

## Acceptance Criteria

1. Text and password fields use the same editing helper.
2. Users can insert characters at the cursor instead of only appending.
3. Backspace deletes before the cursor and Delete deletes at the cursor.
4. Ctrl+U clears the field.
5. Home/End and Ctrl+A/Ctrl+E move to beginning/end.
6. Pasted printable text is inserted at the cursor.
7. Esc cancels the edit without changing the field.
8. Existing tests pass, with focused unit coverage for editing keys and form-loop integration.

## Technical Design

Keep the implementation in `tui.py`:

- Add a small pure-ish key handler that transforms `(value, cursor, key)` into an updated state or a commit/cancel action.
- Add a curses-backed field editor that renders the current visible slice and cursor position.
- Replace the duplicated text/password loops in `_run_form_loop()` with the shared editor.

Password fields should keep masking display text but use the same cursor and mutation logic as text fields.

## Review Status

- status: reviewed
- verdict: PASS
- notes: This is a high-frequency TUI polish change with contained implementation risk.
