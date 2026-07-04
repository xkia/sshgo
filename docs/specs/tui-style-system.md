# TUI style system

## Metadata

- slug: tui-style-system
- status: approved
- owner: PM/Architect/Engineer
- related_roadmap: docs/roadmap.md#2026-07
- related_docs:
  - docs/gap-analysis.md
- related_specs:
  - docs/specs/common-workflow-polish.md

## Background

The TUI currently mixes several rendering styles:

- the main host list draws directly on the screen
- forms draw a separate ASCII inner box with fixed coordinates
- messages use ad hoc one-off screens
- the detail pane is drawn as a floating overlay after the list

That makes the interface feel inconsistent and makes future TUI changes harder to maintain. The goal is to establish one reusable TUI template for daily host browsing and editing, without changing connection behavior.

## Scope

- Introduce shared TUI layout helpers for title, content area, status/footer bar, message screens, and safe text drawing.
- Use one form layout template for add/edit/delete/confirm flows.
- Make form field placement flow from the template instead of relying on fixed per-form coordinates.
- Keep the main list and detail pane in a split layout when there is enough width, so details do not cover the list.
- Keep all existing keyboard shortcuts and form behavior.
- Preserve stdlib-only curses implementation.

## Non-goals

- Do not change SSH/SFTP/relay execution behavior.
- Do not introduce a GUI or web UI.
- Do not add new host-management features.
- Do not add external dependencies.
- Do not start the CommandPlan extraction in this change.

## Acceptance Criteria

1. Main list, forms, messages, and detail pane share the same outer TUI shell.
2. Forms use a single dynamic layout helper and do not depend on hardcoded `y`/`x` values for visual placement.
3. Add/edit/delete/confirm forms still support text, password, radio, static text, and button controls.
4. Text entry uses the dynamic input position and width from the form layout.
5. Detail pane uses a side-by-side split layout and does not overwrite list rows.
6. Messages such as success, duplicate name, readonly edit, and validation errors use a shared message renderer.
7. Existing shortcuts remain unchanged.
8. Existing tests pass, with added coverage for the new form layout and split layout decisions.

## Technical Design

`tui.py` should keep curses rendering local to the `Tui` class, but split repeated drawing behavior into small helpers:

- safe text drawing and truncation
- shell/header/footer drawing
- message rendering
- form layout calculation
- form rendering from calculated layout
- main/detail split calculation

The form field definitions can keep their existing semantic keys (`label`, `type`, `name`, `required`, `options`, `value`) while layout metadata is derived at draw time.

## Review Status

- status: reviewed
- verdict: PASS
- notes: This is a UI maintainability and daily-use polish change. It intentionally leaves command planning and backend behavior unchanged.
