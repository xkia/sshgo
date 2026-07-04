# SFTP batch mode hardening

## Metadata

- slug: sftp-batch-mode-hardening
- status: in_progress
- owner: PM/Architect/Engineer
- related_roadmap: docs/roadmap.md#future-candidates
- related_docs:
  - docs/gap-analysis.md
- related_specs:
  - docs/specs/common-workflow-polish.md
  - docs/specs/jump-host-connection-modes.md
  - docs/specs/command-planning-extraction.md

## Background

Before this hardening, direct and tunnel SFTP transfers used Expect to open an interactive `sftp>` session, send a single `put` or `get` command, then infer failure from a mix of SFTP output and process exit status.

The current implementation now exits non-zero for common failures, but one residual risk remains: some failure detection still depends on OpenSSH `sftp` text output. That output can vary across OpenSSH versions, platforms, or locale settings.

This proposal reduces that risk by using OpenSSH `sftp` batch mode for single-file direct/tunnel transfers while keeping Expect responsible for password, passphrase, MFA, and host-key prompts.

## Scope

- Change direct/tunnel SFTP transfer execution in `sftp_login.exp` from interactive command send to `sftp -b <batchfile>`.
- Use the `sftp` subprocess exit status as the source of truth for success or failure.
- Keep Expect prompt handling for password, key passphrase, MFA, and host-key confirmation.
- Preserve existing upload/download CLI behavior and transfer jump mode semantics.
- Preserve `--print-command` as a safe preview path that does not create temporary files or expose secrets.
- Keep the current stdlib-only Python and Expect handoff model.

## Non-goals

- Do not implement directory transfer.
- Do not change relay transfer behavior.
- Do not add external dependencies.
- Do not add a Python SFTP implementation.
- Do not supervise transfers from Python after `execve`.
- Do not expand `~/.ssh/config` compatibility.

## Acceptance Criteria

1. Direct SFTP upload/download uses an OpenSSH batch file containing exactly one transfer command.
2. Tunnel SFTP upload/download through supported jump modes uses the same batch-mode path.
3. A non-zero `sftp` process exit causes `sftp_login.exp` to exit non-zero.
4. A successful single-file upload/download exits zero without parsing success text from `sftp` output.
5. Password, key passphrase, MFA, and host-key confirmation flows still work through Expect.
6. Temporary batch files are created with restrictive permissions and removed during cleanup.
7. Existing path validation for newline, carriage return, double quote, and backslash remains in place.
8. Relay transfer behavior and tests remain unchanged.
9. `--print-command` for direct/tunnel upload/download does not create a batch file and does not print passwords, MFA secrets, `SSHGO_*` values, or a real temporary batch-file path.
10. `--print-command` keeps the existing resolved sshgo-to-Expect handoff preview and may include a sanitized one-line batch command preview such as `put "<local>" "<remote>"` or `get "<remote>" "<local>"`.
11. Tests cover success, connect failure, transfer failure, print-command preview, temporary-file handling, and path-name false-positive cases without relying on English SFTP diagnostics for success/failure.

## Technical Design

### Batch File Creation

`sftp_login.exp` should create a temporary batch file before spawning `sftp`:

```text
upload:   put "<local_path>" "<remote_path>"
download: get "<remote_path>" "<local_path>"
```

The file should be owned by the current user, written with mode `0600`, and deleted from `cleanup` regardless of success or failure.

The existing Python-side SFTP path guard should remain unchanged. Because paths containing double quote or backslash are already rejected before handoff, the batch command can continue using the current simple quoted path form.

### SFTP Command

The spawned command should add batch mode:

```text
sftp -b <batchfile> ...
```

The existing options should stay intact:

- `-S sftp_ssh_wrapper.py`
- `ConnectTimeout`
- `StrictHostKeyChecking`
- `UserKnownHostsFile` when strict checking is disabled
- `-P`
- `-i`
- direct custom `ProxyCommand`
- tunnel-generated `ProxyCommand`

OpenSSH `sftp -b` injects `BatchMode=yes` into the underlying ssh command. That breaks password, passphrase, and keyboard-interactive/MFA prompts. `sftp_login.exp` should therefore launch `sftp` with `-S sftp_ssh_wrapper.py`. The wrapper must remove only `BatchMode=yes`, prepend `BatchMode=no`, preserve the remaining ssh arguments, and then `execvp("ssh", ...)`.

### Command Preview

`--print-command` should remain a dry-run diagnostic. It must not create the temporary batch file because doing so would leave preview-only filesystem state and would make the printed command depend on an ephemeral path.

The preview should continue to show the resolved sshgo-to-Expect handoff command used by the CLI. It may also print a sanitized batch command preview for clarity, but that preview must be derived from already-validated local/remote paths and must not include credentials, MFA secrets, `SSHGO_*` environment values, or the real temporary batch-file path.

### Expect Responsibilities

Expect should continue to handle:

- unknown host confirmation
- password/passphrase prompts
- MFA/OTP prompts
- early connection failures
- timeout
- process EOF and `wait` exit status

Expect should no longer need to wait for a post-transfer `sftp>` prompt or send `bye`; batch mode exits after the batch file completes.

### Failure Semantics

The `sftp` process exit status should determine transfer success:

- exit `0`: transfer succeeded
- exit non-zero: transfer failed
- EOF before an authenticated session opens: fail with a connection/session message
- timeout: fail with a timeout message

Output text may still be shown to the user as context, but it should not be required to decide success or failure.

## Tradeoffs

### Benefits

- More reliable failure detection because OpenSSH owns transfer success semantics.
- Lower false-positive risk from file names containing words like `error`, `failed`, or `Permission denied`.
- Cleaner separation: Expect handles authentication; OpenSSH `sftp` handles transfer execution.
- No new runtime dependencies.
- Tests can focus on exit codes instead of localized output strings.

### Costs and Risks

- Batch mode must be manually smoke-tested with password, key passphrase, and MFA prompts.
- Error messages may be less specific unless raw `sftp` output is preserved for display.
- Temporary batch file lifecycle must be correct to avoid stale path data.
- Any OpenSSH batch-mode behavior difference from interactive single-command mode must be caught before release.

## Test Plan

- Unit-style fake `sftp` tests:
  - connect failure before authentication prompt
  - transfer failure with non-zero exit
  - transfer success with paths containing words such as `error` or `failed`
  - generated batch file has mode `0600`
  - generated batch file contains exactly one expected `put` or `get` command
  - cleanup removes the temporary batch file
  - cleanup removes the temporary batch file when `sftp` cannot be spawned
  - cleanup removes the temporary batch file after `INT`, `TERM`, and `HUP`
  - startup removes stale `sshgo-sftp-*.batch` files older than the retention threshold
- Preview tests:
  - `--print-command` does not create a temporary batch file
  - preview output keeps the resolved Expect handoff command
  - preview output does not include passwords, MFA secrets, `SSHGO_*`, or real temporary batch-file paths
- Command-plan regression:
  - direct SFTP keeps existing host, port, key, proxy, and host-key options
  - tunnel SFTP keeps generated proxy command behavior
  - real `sftp -S sftp_ssh_wrapper.py -b <batch>` with a fake `ssh` does not pass `BatchMode=yes` to ssh
- Manual smoke:
  - host-key confirmation on a new host
  - direct password upload/download
  - direct key/passphrase upload/download
  - tunnel upload/download through a jump host
  - one MFA-protected login path if available

## Rollout

1. Implement behind the existing direct/tunnel SFTP path without adding a user-facing flag.
2. Keep relay transfers unchanged.
3. Run the full unit suite plus manual direct/tunnel transfer smoke checks.
4. If batch mode breaks a real auth flow, revert only `sftp_login.exp` and its tests because command planning and user-facing config should not need to change.

## Review Status

- status: reviewed
- verdict: PASS
- notes: Implementation is in progress on `feature/sftp-batch-mode-hardening`; scope remains limited to direct/tunnel single-file SFTP hardening.
