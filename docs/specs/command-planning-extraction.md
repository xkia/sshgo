# Command planning extraction

## Metadata

- slug: command-planning-extraction
- status: approved
- owner: Architect/Engineer
- related_roadmap: docs/roadmap.md#future-candidates
- related_docs:
  - docs/gap-analysis.md
- related_specs:
  - docs/specs/cli-safety-and-diagnostics.md
  - docs/specs/common-workflow-polish.md
  - docs/specs/jump-host-connection-modes.md
  - docs/specs/custom-proxy-command.md

## Background

`HostManager` currently builds SSH, SFTP, and relay launch arguments directly in the same paths that record audit events and call `os.execve()`. That keeps behavior compact, but it makes launch behavior harder to test without patching process execution.

This change extracts the launch data into a small pure command plan object while preserving the current Expect handoff model.

## Scope

- Add a `CommandPlan` data object for resolved handoff script path, argv, secret environment values, audit metadata, and failure result labels.
- Add plan builders for interactive SSH and file transfer launch paths.
- Make existing preview and execution paths consume those plans.
- Keep existing public command-argument builder methods as compatibility wrappers.
- Add tests that inspect command plans without patching `os.execve`.

## Non-goals

- Do not change Expect scripts or handoff semantics.
- Do not supervise SSH/SFTP/relay sessions from Python.
- Do not add final-result audit events.
- Do not change `--print-command` output except by preserving the same rendered argv through a plan.
- Do not add external dependencies.

## Acceptance Criteria

1. Interactive SSH launch data can be built as a `CommandPlan`.
2. SFTP and relay transfer launch data can be built as a `CommandPlan`.
3. A command plan exposes script path, launch argv, secret environment values, and audit metadata without requiring `os.execve`.
4. `build_interactive_launch_command_args()` and `build_file_transfer_launch_command_args()` remain available and return the same argv shape as before.
5. Execute paths use command plans for audit, environment construction, and `execve`.
6. Secret values are still excluded from printed command previews.
7. Existing tests pass and new tests cover interactive, SFTP, and relay command plans.

## Technical Design

Keep `CommandPlan` in `host_manager.py` for now to avoid a broad module split. It should be a small stdlib dataclass with:

- `script_path`
- `args`
- `secret_env`
- `audit`
- `start_result`
- `missing_result`
- `exec_failed_prefix`
- optional user-facing failure messages

`launch_args()` returns `[script_path] + args` for preview and `execve`.

The current low-level builders can continue producing `(args, logical_secrets)` for SSH/SFTP/relay. Plan builders convert logical secret names into the existing `SSHGO_*` environment names and add audit metadata. A shared executor can then record start/failure audit events and call `os.execve()`.

## Review Status

- status: reviewed
- verdict: PASS
- notes: The refactor reduces HostManager coupling without changing user-visible command behavior.
