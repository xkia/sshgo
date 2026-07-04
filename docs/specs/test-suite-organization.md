# Test suite organization

## Metadata

- slug: test-suite-organization
- status: approved
- owner: Engineer
- related_roadmap: docs/roadmap.md#2026-07
- related_specs:
  - docs/specs/command-planning-extraction.md
  - docs/specs/tui-input-editing-polish.md

## Background

`tests/test_connection_auth_audit.py` has accumulated coverage for CLI, audit, command planning, transfer modes, validation, and TUI behavior. The file still works, but adding more focused tests to it makes future changes harder to navigate.

## Scope

- Split low-risk slices of tests into focused modules.
- CommandPlan tests live in a focused module because they are isolated and do not require process monkeypatching.
- TUI layout, input-editing, rendering, navigation, Recent, and add/edit/delete flow tests live in a focused module because they use fake screens and temporary configs instead of process monkeypatching.
- Audit retention and audit identity tests live in a focused module because they have a compact runtime-data fixture.
- Validation schema, validate-style load, and candidate-validation tests live in a focused module because they use pure config fixtures or in-memory HostManager candidates.
- CLI shortcut, print-command, default config path, and doctor tests live in a focused module because they exercise `sshgo.py` entry behavior.
- HostManager persistence and CRUD cleanup tests live in a focused module because they validate config writes and node mutation rules without Expect handoff.
- SFTP Expect script tests live in a focused module because they exercise batch, wrapper, prompt, cleanup, and interactive `sftp>` behavior without sharing the broader connection/audit fixture.
- Relay transfer script tests live in a focused module because they exercise relay-specific Expect behavior and quoting without sharing the broader connection/audit fixture.
- Keep unittest discovery and existing verification commands unchanged.

## Non-goals

- Do not rewrite the whole test suite.
- Do not change product behavior.
- Do not introduce pytest or external test dependencies.
- Do not move tests that require large fixture redesign in this slice.

## Acceptance Criteria

1. CommandPlan tests live in a focused test module.
2. TUI layout, input-editing, rendering, navigation, Recent, and add/edit/delete flow tests live in a focused test module.
3. Audit retention and audit identity tests live in a focused test module.
4. Validation schema, validate-style load, and candidate-validation tests live in a focused test module.
5. CLI shortcut, print-command, default config path, and doctor tests live in a focused test module.
6. HostManager persistence and CRUD cleanup tests live in a focused test module.
7. SFTP Expect script tests live in a focused test module.
8. Relay transfer script tests live in a focused test module.
9. Existing unittest discovery still finds all tests.
10. The total behavior coverage is preserved.

## Technical Design

Create focused modules with local fixture helpers:

- `tests/test_command_plan.py`
- `tests/test_tui.py`
- `tests/test_audit.py`
- `tests/test_validation.py`
- `tests/test_cli.py`
- `tests/test_host_manager.py`
- `tests/test_expect_sftp.py`
- `tests/test_relay_transfer.py`

Leave shared fixture extraction for a later cleanup only if more test modules need it.

## Review Status

- status: reviewed
- verdict: PASS
- notes: This is a minimal organization slice that improves maintainability without broad churn.
