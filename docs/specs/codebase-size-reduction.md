# Codebase Size Reduction

## Metadata

- slug: codebase-size-reduction
- status: superseded
- owner: Engineer
- superseded_by:
  - docs/specs/final-2-0-optimization-audit.md
  - docs/specs/internal-refactors-and-tests.md
- related_specs:
  - docs/specs/host-port-schema-split.md
  - docs/specs/review-compatibility-hardening.md

## Outcome

This spec was the initial cleanup boundary for reducing sshgo's implementation
and documentation weight. It is no longer an active plan. Current decisions live
in `final-2-0-optimization-audit.md`; current module boundaries live in
`internal-refactors-and-tests.md`.

Completed cleanup:

- Separated config storage, validation, host-tree helpers, connection planning,
  runtime handoff, audit logging, TUI helpers, and CLI helper modules.
- Removed development-only command-plan/raw-args compatibility wrappers.
- Removed HostManager private forwarding methods that only wrapped focused
  modules.
- Removed low-value user entry points such as `sshgo --edit` and low-frequency
  config toggles.
- Compressed README and documentation index so active behavior specs are read
  before historical implementation records.

## Retained Decisions

| Area | Decision |
| --- | --- |
| `HostManager` | Keep it as the product facade for config lifecycle, CRUD, validation, encryption, alias lookup, and execute/preview methods |
| `Tui` | Keep curses lifecycle and screen ownership in `tui.py`; move only pure helpers when the boundary is obvious |
| `connection_planner.py` | Keep command-plan construction in one cohesive module; use local helpers for repeated auth args |
| `config_validation.py` | Keep one centralized parsed-config validator; use tables/helpers where they reduce repeated rules |
| Expect scripts | Do not split for line count; only change for concrete prompt, auth, or transfer bugs |
| Tests | Reduce setup duplication with fixtures, but preserve behavior coverage |
| Docs | Keep stable behavior, constraints, risks, and verification entry points; remove completed process logs |

## Verification

Use the broad verification commands in `AGENTS.md`. This superseded document
should not maintain a second checklist.
