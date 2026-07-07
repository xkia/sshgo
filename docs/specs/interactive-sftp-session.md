# Interactive SFTP Session

## Metadata

- slug: interactive-sftp-session
- status: implemented
- owner: PM/Architect/Engineer
- related_roadmap: docs/roadmap.md#2026-07
- related_specs:
  - docs/specs/jump-host-connection-modes.md
  - docs/specs/sftp-batch-mode-hardening.md
  - docs/specs/security-hardening.md

## Problem

`upload` and `download` cover fast, explicit single-file transfer. They do not
cover ad-hoc exploration such as listing remote directories, creating
directories, renaming files, or running several SFTP commands before choosing
what to transfer.

sshgo therefore provides a lightweight escape hatch that launches a normal
OpenSSH `sftp>` prompt while reusing sshgo host resolution, jump-mode planning,
authentication, MFA, host-key policy, and audit-start behavior.

## User Interface

Accepted:

```bash
./sshgo.sh --sftp <alias>
./sshgo.sh --print-command --sftp <alias>
```

Rejected:

```bash
./sshgo.sh --sftp <alias> extra
```

Reserved behavior:

```bash
./sshgo.sh <alias> sftp
```

The positional form remains a normal remote SSH command shortcut. It is not
captured by interactive SFTP.

## Scope

- CLI-only first version.
- Direct hosts open a local interactive `sftp>` prompt.
- Nested hosts work only when effective `transfer_jump_mode=tunnel`.
- Effective `transfer_jump_mode=relay` fails before Expect handoff.
- `--print-command` prints a safe handoff preview without secrets or batch
  files.
- Python records only start and exec-failure audit events, then hands off via
  `os.execve()`.

## Non-Goals

- No TUI remote file browser.
- No recursive or multi-file batch feature.
- No Python SFTP client.
- No supervision of the live SFTP session after handoff.
- No audit of commands typed inside `sftp>`.
- No relay-mode pseudo-SFTP.

## Mode Behavior

| Host shape | Effective transfer mode | Behavior |
| --- | --- | --- |
| Direct host | no jump host | Open local interactive `sftp>` |
| Nested host | `tunnel` | Open local interactive `sftp>` through generated `ProxyCommand` |
| Nested host | `relay` | Reject with a localized error |

Interactive SFTP never uses `sftp -b` and never uses `sftp_ssh_wrapper.py`.
Those are batch upload/download concerns.

## Authentication and Audit

Direct and tunnel interactive SFTP use local OpenSSH semantics:

- global or host-level SSH agent rules may apply;
- `id_file` paths are local paths;
- local known-hosts policy applies;
- password, key passphrase, host-key prompt, and MFA/TOTP handling remain in
  Expect.

Audit labels:

```text
sftp_interactive_started
sftp_interactive_exp_not_found
sftp_interactive_exec_failed
```

Final exit status, session duration, transferred paths, and commands typed
inside `sftp>` are not recorded.

## Implementation Boundary

`connection_planner.py` owns interactive SFTP command-plan construction.
`sftp_login.exp` owns prompt handling and switches behavior based on interactive
vs batch mode:

- interactive mode builds `sftp` without `-b`;
- it waits for the first successful `sftp>` prompt;
- it then hands control to the user with `interact`;
- EOF/timeout before the first prompt is treated as startup failure.

Relay rejection happens before `execve`.

## Acceptance Criteria

1. `--sftp <alias>` opens an interactive prompt for direct hosts.
2. `--sftp <alias>` opens an interactive prompt for nested tunnel hosts.
3. relay mode is rejected before handoff with a localized message.
4. batch upload/download behavior is unchanged.
5. `--print-command --sftp <alias>` is safe and creates no batch file.
6. password, passphrase, host-key prompt, MFA, and SSH agent paths remain
   supported.
7. alias ambiguity and unsupported topology checks remain enforced.
8. no external Python dependencies are added.

## Verification

Use the broad verification commands in `AGENTS.md`. Focused tests should cover
CLI parsing, safe preview, direct/tunnel command shape, relay rejection,
no-batch interactive args, prompt handling, EOF/timeout before prompt, and
regression coverage for existing upload/download paths.

## Review Status

- status: implemented
- verdict: PASS
- notes: Open questions and implementation alternatives were resolved; this
  document now records the stable CLI behavior and maintenance boundary.
