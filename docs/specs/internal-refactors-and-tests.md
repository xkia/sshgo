# Internal Refactors And Tests

## Metadata

- slug: internal-refactors-and-tests
- status: reviewed
- owner: Architect/Engineer
- related_roadmap: docs/roadmap.md#2026-07
- replaces: completed config storage, validation, host-tree, connection planning, HostManager decomposition, project cohesion, and test organization specs

## Purpose

This spec records the accepted internal module and test-suite boundaries after the 2026-07 behavior-preserving refactor work. It replaces several completed implementation-plan specs so future maintainers can see the current design without reading historical round-by-round plans.

## Scope

- Keep user-visible SSH, SFTP, relay, config, audit, encryption, and TUI behavior unchanged.
- Keep Python stdlib-only.
- Keep `HostManager` as the public facade for CLI and TUI callers.
- Keep compatibility exports from `host_manager.py` where existing code or tests import them.
- Keep `sshgo.py` as the only script entry point.
- Keep unittest discovery through `python3 -m unittest discover -s tests -p 'test*.py'`.

## Accepted Module Boundaries

| Area | Module | Responsibility |
|---|---|---|
| CLI entry | `sshgo.py` | Arg parsing, high-level dispatch, shortcut handling, TUI launch, and compatibility wrappers around CLI helpers |
| CLI config | `cli_config.py` | Config path probing, backup list/restore helpers, and saved-node ID migration gating |
| CLI diagnostics | `cli_diagnostics.py` | `--doctor` dependency, terminal, runtime-data, and config snapshot checks |
| Config storage | `config_store.py` | JSONC read support, atomic JSON writes, stale-write fingerprints, and backup rotation/list/restore |
| Config validation | `config_validation.py` | Pure parsed-config validation, placeholder/jump-mode constants, and localized validation messages |
| Host tree | `host_tree.py` | Pure traversal, lookup, replacement, parent/index lookup, runtime parent-link rebuilding, and node ID assignment helpers |
| Host facade | `host_manager.py` | Config lifecycle, encryption/decryption, CRUD, validation delegation, alias lookup, compatibility wrappers, and user-facing execute/preview methods |
| Connection errors | `connection_errors.py` | Shared runtime/config exceptions |
| Connection plan | `connection_plan.py` | `CommandPlan`, secret environment mapping, and UTF-8 locale normalization for Expect handoff |
| Connection planner | `connection_planner.py` | SSH, SFTP, interactive SFTP, and relay `CommandPlan` construction without importing `host_manager.py` |
| Connection runtime | `connection_runtime.py` | Executable checks, optional terminal title emission, audit start/failure records, environment construction, and `os.execve()` handoff |
| TUI helpers | `tui_text.py`, `tui_forms.py` | Pure text-editing helpers and form schema/form-data conversion helpers |

## Compatibility Rules

- `from host_manager import CommandPlan`, `ConfigRuntimeError`, `PlaceholderResolutionError`, and `validate_hosts_config` remain supported.
- `HostManager` public preview and execution methods keep existing signatures.
- Existing public `HostManager.build_*` compatibility wrappers remain stable, including SSH launch args, file-transfer launch args, SFTP transfer args, interactive/SFTP/relay command plans, and their launch-argv helpers.
- `sshgo.run_doctor()` and `sshgo.run_doctor_for_path()` keep using the current `sshgo.Tui`, `sshgo.shutil.which`, and `sshgo.HostManager` bindings so existing tests and local monkeypatching patterns remain compatible.
- `connection_planner.py` may consume a structural adapter object, but it must not import `host_manager.py`.
- Python still hands live SSH/SFTP/relay sessions to Expect via `execve`; final session status is not supervised by Python.

## Test Organization

Focused test files are the accepted organization boundary:

- `tests/test_command_plan.py`
- `tests/test_tui.py`
- `tests/test_tui_text.py`
- `tests/test_tui_forms.py`
- `tests/test_audit.py`
- `tests/test_config_backup.py`
- `tests/test_config_store.py`
- `tests/test_config_validation.py`
- `tests/test_validation.py`
- `tests/test_cli.py`
- `tests/test_host_manager.py`
- `tests/test_host_tree.py`
- `tests/test_terminal_title.py`
- `tests/test_expect_sftp.py`
- `tests/test_relay_transfer.py`

`tests/test_connection_auth_audit.py` remains for cross-cutting auth, audit, runtime, terminal-title, and command-construction coverage. Do not move more tests out of it unless the split is mechanical and preserves all assertions.

## Non-goals

- Do not split into a package directory without a separate spec.
- Do not remove compatibility exports from `host_manager.py` in this version.
- Do not add dependencies or replace unittest.
- Do not rewrite `Tui` into several stateful classes just to reduce line count.
- Do not change config, audit, Expect, jump-host, or transfer semantics as part of internal cleanup.

## Verification

For broad internal refactor or documentation-boundary changes:

```bash
python3 -m unittest discover -s tests -p 'test*.py'
python3 -m py_compile sshgo.py cli_config.py cli_diagnostics.py host_manager.py host_tree.py config_store.py config_validation.py tui.py tui_text.py tui_forms.py audit_logger.py auth.py crypto.py config_parser.py i18n.py terminal_title.py connection_errors.py connection_plan.py connection_planner.py connection_runtime.py sftp_ssh_wrapper.py tests/test_connection_auth_audit.py tests/test_command_plan.py tests/test_terminal_title.py tests/test_tui.py tests/test_tui_text.py tests/test_tui_forms.py tests/test_expect_sftp.py tests/test_relay_transfer.py tests/test_audit.py tests/test_config_backup.py tests/test_config_store.py tests/test_config_validation.py tests/test_validation.py tests/test_cli.py tests/test_host_manager.py tests/test_host_tree.py
python3 sshgo.py --validate
git diff --check
```

## Review Status

- status: reviewed
- verdict: PASS
- notes: Consolidated from completed internal refactor specs. The current design keeps behavior stable while documenting the module and test boundaries that matter going forward.
