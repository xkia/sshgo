# Host Manager Decomposition

## Metadata

- slug: host-manager-decomposition
- status: approved
- owner: Architect/Engineer
- related_roadmap: docs/roadmap.md#2026-07
- related_docs:
  - docs/gap-analysis.md
- related_specs:
  - docs/specs/command-planning-extraction.md
  - docs/specs/terminal-title.md
  - docs/specs/jump-host-connection-modes.md
  - docs/specs/custom-proxy-command.md
  - docs/specs/interactive-sftp-session.md

This spec supersedes the temporary `CommandPlan` placement note in `docs/specs/command-planning-extraction.md`; `CommandPlan` may move out of `host_manager.py` as long as `host_manager.py` keeps the compatibility export.

## Problem Background

`host_manager.py` remains sshgo's main facade, but it has accumulated several responsibilities: config lifecycle, host/group CRUD, validation glue, encryption, alias resolution, connection planning, command-plan execution, audit handoff, terminal title emission, and Expect process replacement.

Some responsibilities have already been moved out (`config_store.py`, `config_validation.py`, `host_tree.py`, `audit_logger.py`, `terminal_title.py`). The next decomposition should continue that pattern without changing user-visible behavior or forcing TUI/CLI callers to understand low-level connection internals.

## Scope

- Keep `HostManager` as the public facade for CLI and TUI callers.
- Move connection-specific data objects, errors, runtime execution, and planner logic into focused modules.
- Preserve compatibility imports from `host_manager.py` for `CommandPlan`, `ConfigRuntimeError`, `PlaceholderResolutionError`, and `validate_hosts_config`.
- Keep all public `HostManager` methods used by CLI/TUI/tests available.
- Keep the Expect `execve` handoff model unchanged.
- Use friendlier domain names for new files:
  - `connection_errors.py`
  - `connection_plan.py`
  - `connection_runtime.py`
  - `connection_planner.py`
- Keep existing independent filenames that are already clear:
  - `config_store.py`
  - `config_validation.py`
  - `host_tree.py`
  - `audit_logger.py`
  - `terminal_title.py`

## Non-goals

- Do not rewrite host/group CRUD in this change.
- Do not change config format, validation rules, encryption format, audit schema, or Expect scripts.
- Do not add package dependencies.
- Do not change CLI/TUI behavior, shortcut resolution, command previews, or SFTP/relay semantics.
- Do not split into a Python package directory yet; keep the flat module layout.
- Do not remove `host_manager.py` compatibility exports in this version.

## Target Module Boundaries

| Module | Responsibility |
|---|---|
| `host_manager.py` | Public facade: config lifecycle, encryption toggle, host/group CRUD, alias lookup, user-facing execute/preview methods, compatibility exports |
| `connection_errors.py` | Shared connection/config runtime exceptions used by planner/runtime/facade |
| `connection_plan.py` | `CommandPlan`, secret environment mapping, UTF-8 locale helpers, and launch environment construction |
| `connection_runtime.py` | Execute a `CommandPlan`: ensure script executable, emit terminal title, record audit start/failure, call `os.execve()` |
| `connection_planner.py` | Build SSH, SFTP, interactive SFTP, and relay `CommandPlan` instances from resolved host nodes |
| `terminal_title.py` | Terminal title formatting/detection/OSC output before handoff |

`connection_planner.py` must not import `host_manager.py`. It should receive the narrow domain operations it needs from `HostManager` through constructor arguments or lightweight adapter callbacks. The first implementation may pass the existing `HostManager` instance as a private adapter object only if `connection_planner.py` treats it structurally and never imports the class. Longer-term extraction should move those adapter methods into smaller modules when doing so reduces real coupling.

## Phased Implementation

### Round 1: Plan Object And Errors

- Add `connection_errors.py`.
- Add `connection_plan.py`.
- Move `CommandPlan`, secret env key mapping, secret env construction, and UTF-8 locale normalization out of `host_manager.py`.
- Keep `host_manager.py` importing and re-exporting moved names.
- Keep command-plan tests passing without changing user behavior.
- Run focused verification and an independent review agent.

### Round 2: Runtime Executor

- Add `connection_runtime.py`.
- Move executable checks, plan audit recording, terminal title emission, environment construction, and `execve` error handling into a `ConnectionRuntime` helper.
- `HostManager._execute_command_plan()` becomes a thin delegate.
- Preserve start/exec-failure audit ordering and results.
- Run focused verification and an independent review agent.

### Round 3: Connection Planner

- Add `connection_planner.py`.
- Move SSH/SFTP/interactive-SFTP/relay argument construction and plan builders into a `ConnectionPlanner` helper.
- Keep `HostManager` methods as stable wrappers:
  - `build_ssh_command_args`
  - `build_file_transfer_command_args`
  - `build_sftp_command_args`
  - `build_interactive_command_plan`
  - `build_sftp_command_plan`
  - `build_interactive_sftp_command_plan`
  - `build_relay_command_plan`
  - `build_file_transfer_command_plan`
  - `build_*_launch_command_args`
- Avoid circular imports: planner/runtime modules may depend on `connection_*`, `config_validation`, `i18n`, and `terminal_title`, but must not import `host_manager.py`.
- Run focused verification and an independent review agent.

## Acceptance Criteria

1. `HostManager` remains the only object TUI/CLI need for common workflows.
2. Existing public `HostManager` connection and preview APIs keep the same signatures and behavior.
3. `CommandPlan`, `ConfigRuntimeError`, `PlaceholderResolutionError`, and `validate_hosts_config` remain importable from `host_manager.py`.
4. Command previews do not emit terminal title sequences.
5. SSH, interactive SFTP, SFTP transfer, and relay transfer build the same launch args and audit metadata as before.
6. Secrets remain excluded from printed command previews and are passed only through transient `SSHGO_*` environment values.
7. UTF-8 locale normalization for Expect handoff remains intact.
8. Every implementation round receives an independent review before proceeding.
9. `AGENTS.md`, `docs/README.md`, and related specs describe the final module boundaries.
10. Full verification passes after all rounds.

## Test Plan

- Focused after Round 1:
  - `python3 -m unittest tests.test_command_plan tests.test_connection_auth_audit`
  - `python3 -m py_compile host_manager.py connection_errors.py connection_plan.py`
- Focused after Round 2:
  - `python3 -m unittest tests.test_connection_auth_audit tests.test_audit tests.test_terminal_title`
  - `python3 -m py_compile host_manager.py connection_runtime.py connection_plan.py terminal_title.py`
- Focused after Round 3:
  - `python3 -m unittest tests.test_command_plan tests.test_connection_auth_audit tests.test_cli`
  - `python3 -m py_compile host_manager.py connection_planner.py connection_runtime.py connection_plan.py connection_errors.py`
- Final:
  - `python3 -m unittest discover -s tests -p 'test*.py'`
  - `python3 -m py_compile sshgo.py host_manager.py host_tree.py config_store.py config_validation.py tui.py audit_logger.py auth.py crypto.py config_parser.py i18n.py terminal_title.py connection_errors.py connection_plan.py connection_runtime.py connection_planner.py sftp_ssh_wrapper.py tests/test_connection_auth_audit.py tests/test_command_plan.py tests/test_terminal_title.py tests/test_tui.py tests/test_audit.py tests/test_config_backup.py tests/test_config_store.py tests/test_config_validation.py tests/test_validation.py tests/test_cli.py tests/test_host_manager.py tests/test_host_tree.py`
  - `python3 sshgo.py --validate`
  - `git diff --check`

## Review Status

- status: approved
- verdict: PASS
- notes: The plan keeps `HostManager` as a compatibility facade while moving connection-specific complexity into focused modules through reviewable, behavior-preserving rounds.
