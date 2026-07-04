# Project Cohesion Refactor

## Metadata

- slug: project-cohesion-refactor
- status: approved
- owner: Architect/Engineer
- related_roadmap: docs/roadmap.md#2026-07
- related_docs:
  - docs/gap-analysis.md
- related_specs:
  - docs/specs/host-manager-decomposition.md
  - docs/specs/tui-style-system.md
  - docs/specs/cli-safety-and-diagnostics.md
  - docs/specs/test-suite-organization.md

## Current Assessment

The repository now has clear domain modules for config storage, config validation, host tree helpers, audit logging, connection planning, connection runtime, terminal titles, and authentication. The remaining coordination issues are concentrated in a few large files and mixed-purpose entry points.

| Area | Current State | Risk | Refactor Direction |
|---|---|---|---|
| `tui.py` | 1900+ lines; owns screen lifecycle, rendering primitives, form schemas, form loop, add/edit/delete flows, list navigation, recent construction, and detail pane | Medium | Split pure helpers and form schema/building first; keep `Tui` facade stable |
| `host_manager.py` | 1200+ lines after connection split; still owns config lifecycle, crypto, CRUD, lookup, compatibility wrappers | Low/Medium | Do not split again until TUI/CLI are cleaner; remaining responsibilities still fit facade role |
| `sshgo.py` | 600+ lines; mixes argparse, shortcut dispatch, TUI launch, config path resolution, backups, history, doctor diagnostics | Medium | Extract CLI support modules around diagnostics and config-path/backup/history helpers |
| `tests/test_connection_auth_audit.py` | 2000+ lines; mixes Expect script behavior, SFTP batch behavior, relay behavior, runtime audit, terminal title integration | Medium | Split SFTP/relay behavior families without changing assertions |
| Documentation | Specs are mostly consistent; new module boundaries must stay reflected in `AGENTS.md` and docs index | Low | Keep docs synced with every moved boundary |
| Naming | Current domain names are mostly clear: `config_*`, `host_tree`, `connection_*`, `terminal_title` | Low | Avoid broad renames; only rename when a module name hides responsibility |

## Scope

- Keep behavior unchanged.
- Improve project coordination by moving cohesive code out of oversized files.
- Keep stdlib-only Python.
- Preserve CLI/TUI public behavior and `HostManager` compatibility exports.
- Review each implementation item independently before moving to the next one.
- Keep every item small enough for focused verification.

## Non-goals

- Do not rewrite the TUI framework.
- Do not redesign config schema, audit schema, Expect scripts, encryption, or jump-host semantics.
- Do not rename clear existing modules just for symmetry.
- Do not split into a package directory yet.
- Do not remove compatibility imports from `host_manager.py`.
- Do not refactor all tests at once.

## Planned Items

### Item 1: CLI Support Extraction

Create focused CLI helper modules while preserving `sshgo.py` as the entry point:

- `cli_config.py`: config path probing, config backup listing/restoring, node-id migration gate.
- `cli_diagnostics.py`: `--doctor` helpers and diagnostic line formatting.
- Optional `cli_shortcuts.py` only if shortcut dispatch starts to grow; otherwise keep shortcut dispatch in `sshgo.py`.

Acceptance:

- `sshgo.py` remains the only script entry point.
- `--doctor`, `--list-backups`, `--restore-backup`, config path resolution, shortcuts, and TUI launch keep behavior.
- `tests/test_cli.py` and `tests/test_config_backup.py` pass, including node-id migration guard and backup helper coverage.
- Independent review after implementation.

### Item 2: TUI Pure Helper Extraction

Move pure or near-pure helpers out of `Tui` without changing curses flow:

- `tui_text.py`: key matching, printable text extraction, cursor-aware text editing, ellipsizing.
- `tui_layout.py`: form layout calculations and split-pane dimensions if they can stay pure.

Acceptance:

- `Tui` still owns curses windows and user flows.
- `tests/test_tui.py` passes.
- Manual TUI behavior is unchanged by code path.
- Independent review after implementation.

### Item 3: TUI Form Schema Extraction

Move add/edit form field construction and form-data conversion to a dedicated module:

- `tui_forms.py`: host/group field schema, clean form data, form-to-node/update conversion.

Acceptance:

- Add/edit/delete UX remains unchanged.
- Existing in-form validation focus behavior remains unchanged.
- Focused tests cover host/group add/edit data conversion, default jump modes not being persisted, proxy command persistence only through allowed fields, and auth field visibility/required state.
- `tests/test_tui.py` and validation tests pass.
- Independent review after implementation.

### Item 4: Test File Cohesion

Split only the largest mixed test file into behavior-focused modules:

- `tests/test_expect_sftp.py`: SFTP Expect/batch/interactive script tests.
- `tests/test_relay_transfer.py`: relay transfer script tests.
- Keep connection plan/audit tests where they are unless a split is mechanical.

Acceptance:

- unittest discovery remains unchanged.
- No assertion behavior is weakened.
- Full test suite passes.
- Independent review after implementation.

### Item 5: Final Naming And Documentation Pass

Review module names, docs index, AGENTS module table, roadmap, and specs after code movement.

Acceptance:

- Names describe responsibility without generic catch-all labels.
- `AGENTS.md` and `docs/README.md` match final module boundaries, including this spec's discoverability in the docs index.
- Full verification passes.
- Independent final review passes.

## Deferred Candidates

- Further `HostManager` decomposition into CRUD/config lifecycle modules. This may be worthwhile later, but after the connection split it is no longer the most urgent coordination problem.
- Full TUI class decomposition into multiple collaborating classes. This is higher risk than extracting pure helpers first.
- Broad test fixture framework changes. Current tests are verbose but effective; avoid rewriting fixtures without a clear defect.

## Verification

Per item:

```bash
python3 -m unittest <focused test modules>
python3 -m py_compile <touched modules>
git diff --check
```

Final:

```bash
python3 -m unittest discover -s tests -p 'test*.py'
python3 -m py_compile sshgo.py cli_config.py cli_diagnostics.py host_manager.py host_tree.py config_store.py config_validation.py tui.py tui_text.py tui_forms.py audit_logger.py auth.py crypto.py config_parser.py i18n.py terminal_title.py connection_errors.py connection_plan.py connection_planner.py connection_runtime.py sftp_ssh_wrapper.py tests/test_connection_auth_audit.py tests/test_command_plan.py tests/test_terminal_title.py tests/test_tui.py tests/test_tui_text.py tests/test_tui_forms.py tests/test_expect_sftp.py tests/test_relay_transfer.py tests/test_audit.py tests/test_config_backup.py tests/test_config_store.py tests/test_config_validation.py tests/test_validation.py tests/test_cli.py tests/test_host_manager.py tests/test_host_tree.py
python3 sshgo.py --validate
git diff --check
```

## Review Status

- status: reviewed
- verdict: PASS
- notes: Implemented as behavior-preserving extractions. Item reviews were run after CLI helper extraction, TUI text helper extraction, TUI form schema extraction, and relay test split; final verification covers the complete project.
