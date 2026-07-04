# Interactive SFTP Session

## Metadata

- slug: interactive-sftp-session
- status: implemented
- owner: PM/Architect/Engineer
- related_roadmap: docs/roadmap.md#2026-07
- related_docs:
  - docs/gap-analysis.md
- related_specs:
  - docs/specs/jump-host-connection-modes.md
  - docs/specs/sftp-batch-mode-hardening.md
  - docs/specs/internal-refactors-and-tests.md
  - docs/specs/security-hardening.md

## Problem Background

sshgo currently supports file transfer through explicit single-file commands:

```bash
./sshgo.sh <alias> upload <local> <remote>
./sshgo.sh <alias> download <remote> <local>
```

This is the right default for common, repeatable operations because it is fast, explicit, and easy to audit as a start event. It does not cover ad-hoc SFTP usage where the user needs to inspect a remote directory, create a directory, rename a file, or run several SFTP commands before deciding what to transfer.

The missing capability is not a full remote file manager. The useful gap is a lightweight escape hatch that opens a normal OpenSSH `sftp>` session using sshgo's existing host resolution, jump-host planning, authentication, MFA, host-key policy, and audit-start behavior.

## Positioning

Interactive SFTP should be an advanced entry point, not the primary transfer workflow.

- Keep `upload` and `download` as the optimized common path.
- Add interactive SFTP for exploratory or irregular transfer sessions.
- Do not build a TUI file browser or remote file manager.
- Do not expand the low-frequency feature surface beyond launching a standard `sftp>` prompt.

## Scope

- Add a non-conflicting CLI shortcut to open an interactive SFTP session:

```bash
./sshgo.sh --sftp <alias>
```

- Reuse existing alias resolution and ambiguity protection.
- Reuse existing direct/tunnel SFTP command planning where possible.
- Reuse existing authentication behavior:
  - password
  - key file
  - key passphrase prompts
  - MFA/TOTP prompt-time generation
  - strict host-key handling
  - global/local SSH agent rules
- Support direct hosts.
- Support nested hosts when effective `transfer_jump_mode` is `tunnel`.
- Record an audit start event such as `sftp_interactive_started`.
- Preserve the Python-to-Expect `execve` handoff model.
- Add safe `--print-command` preview support for the interactive SFTP launch.

## Non-goals

- Do not add a TUI remote file browser.
- Do not implement recursive directory transfer.
- Do not add multi-file batch commands.
- Do not add a Python SFTP client.
- Do not supervise the live SFTP session from Python after `execve`.
- Do not record per-command operations entered inside `sftp>`.
- Do not make `relay` behave like SFTP.
- Do not change the existing `upload` / `download` command behavior.

## User Experience

### CLI

```bash
./sshgo.sh --sftp prod-api
```

Expected result:

- sshgo resolves `prod-api`.
- sshgo records a start audit event.
- sshgo opens a standard OpenSSH interactive SFTP prompt.
- The user sees and controls the normal `sftp>` session.

Example session:

```text
Connecting to deploy@prod-api.example.com for interactive sftp...
sftp> pwd
sftp> ls
sftp> put local.log /tmp/local.log
sftp> bye
```

### Preview

```bash
./sshgo.sh --print-command --sftp prod-api
```

Expected result:

- Print the resolved sshgo-to-Expect handoff command.
- Do not print passwords, MFA secrets, or `SSHGO_*` values.
- Do not create temporary files.
- Do not include any batch-file path, because interactive SFTP does not need a batch file.

### TUI

No first-version TUI command is required.

If later useful, the TUI may show a small detail/action hint for the selected host, but it should not embed a file browser. The CLI shortcut remains the source of truth for the first version.

### Remote Command Compatibility

The shortcut form must not reserve `sftp` as a positional action after an alias.

This existing behavior must remain valid:

```bash
./sshgo.sh prod-api sftp
```

It means "SSH to `prod-api` and run remote command `sftp`", exactly like any other remote command shortcut. Interactive SFTP uses `--sftp` specifically to avoid this breaking grammar change.

## Mode Behavior

| Host shape | Effective transfer mode | Behavior |
|---|---|---|
| Direct host | no jump host | Open interactive local `sftp>` to target |
| Nested host | `tunnel` | Open interactive local `sftp>` through generated `ProxyCommand` |
| Nested host | `relay` | Reject with a clear message |

`relay` must be rejected because it is not SFTP. It copies files through a jump-host temporary path with `scp`; it cannot provide a live `sftp>` prompt to the target.

## Command Shape

The interactive SFTP path should not use `sftp -b` and should not use `sftp_ssh_wrapper.py`.

Batch mode was introduced for deterministic single-file `upload` / `download` status handling. Interactive SFTP must keep OpenSSH's normal interactive behavior:

```text
sftp [options] user@host
```

The command should preserve existing direct/tunnel options:

- `ConnectTimeout`
- `StrictHostKeyChecking`
- `UserKnownHostsFile` when strict checking is disabled
- `-P`
- `-i`
- direct custom `ProxyCommand`
- tunnel-generated `ProxyCommand`

## Authentication Semantics

Direct and tunnel interactive SFTP run from the local machine, so they follow local OpenSSH semantics:

- Global `config.use_ssh_agent=true` may satisfy authentication when `SSH_AUTH_SOCK` is available.
- Host-level `use_ssh_agent` overrides the global setting.
- `id_file` paths are local paths.
- Host key checking uses the local known-hosts environment.

`transfer_jump_mode=relay` is not supported for interactive SFTP. If a user needs remote exploration through a relay-only environment, they should open an interactive SSH shell and use tools available on the jump/target environment manually.

## Audit Semantics

Python can record only the start event and exec failure, consistent with the existing handoff model.

Recommended audit labels:

```text
sftp_interactive_started
sftp_interactive_exp_not_found
sftp_interactive_exec_failed
```

Full audit may include:

- node identity
- endpoint
- transfer mode
- rendered command-plan metadata

It must not attempt to record commands typed inside `sftp>`, transferred paths, final duration, or exit status.

## Technical Design

### CLI Parsing

Add an explicit top-level CLI option:

```text
--sftp <alias>
```

Accepted forms:

```bash
./sshgo.sh --sftp <alias>
./sshgo.sh --print-command --sftp <alias>
```

Rejected forms:

```bash
./sshgo.sh --sftp <alias> extra
```

Compatibility rule:

```bash
./sshgo.sh <alias> sftp
```

continues to mean "run remote command `sftp` over SSH".

### Command Planning

Add a command-plan builder for interactive SFTP, separate from the batch upload/download plan:

```python
build_interactive_sftp_command_plan(node)
```

The plan should share lower-level helpers where practical, but keep the batch transfer plan explicit so upload/download lifecycle and temporary-file behavior remain isolated.

Recommended shape:

- `script_path`: `sftp_login.exp` or a new focused Expect script if separation is cleaner.
- `args`: action marker for interactive mode plus target options.
- `secret_env`: same transient `SSHGO_*` pattern as existing transfer paths.
- `audit`: new `sftp_interactive_started` action/result.

### Expect Script Strategy

Two implementation options are acceptable:

1. Extend `sftp_login.exp` with an interactive action.
2. Add a small `sftp_interactive.exp` script.

Preferred first version: extend `sftp_login.exp` only if the branching stays small and readable. If batch-mode cleanup, temporary files, and interactive behavior make the script harder to reason about, use a separate script.

Interactive mode must:

- build `sftp` without `-b`
- not create a batch file
- use the same prompt handling for password/passphrase/MFA/host-key confirmation
- detect the first successful `sftp>` prompt and then call `interact`
- cleanly restore terminal echo through existing cleanup paths

The interactive expect loop must handle these states explicitly:

| State | Required behavior |
|---|---|
| host-key prompt | Send confirmation according to existing behavior, then continue |
| password/passphrase prompt | Send queued secret when available, otherwise hand control to the user |
| MFA/OTP prompt | Generate/send prompt-time code when configured, otherwise hand control to the user |
| first `sftp>` prompt | Restore normal user interaction with `interact` |
| EOF before prompt | Fail with the spawned process exit status or a clear session-start failure |
| timeout before prompt | Fail with a timeout message |
| user exits after `interact` | Wait for child exit status and exit consistently |

This success-prompt branch is required for all auth paths, including agent/no-prompt authentication where the first meaningful signal may be `sftp>` itself.

### Relay Rejection

If a nested target resolves to `transfer_jump_mode=relay`, fail before handoff:

```text
Interactive SFTP requires direct or tunnel transfer mode; relay is not an SFTP session.
```

The message should be localized through `i18n.py`.

## Acceptance Criteria

1. `./sshgo.sh --sftp <alias>` opens an interactive SFTP prompt for a direct host.
2. `./sshgo.sh --sftp <alias>` opens an interactive SFTP prompt for a nested host using effective `transfer_jump_mode=tunnel`.
3. Effective `transfer_jump_mode=relay` fails before Expect handoff with a clear localized message.
4. Existing `upload` and `download` behavior, batch files, cleanup, and tests remain unchanged.
5. `--print-command --sftp <alias>` prints a safe preview and creates no temporary batch file.
6. Password, key passphrase, MFA, and host-key confirmation still work through Expect.
7. Start audit is written before handoff; final SFTP exit status and typed commands are not recorded.
8. Alias ambiguity and unsupported deep jump topology checks remain enforced.
9. No external Python dependencies are added.
10. `./sshgo.sh <alias> sftp` remains a remote SSH command shortcut and is not captured by interactive SFTP.

## Test Plan

- CLI parsing tests:
  - accepts `--sftp <alias>`
  - rejects extra positional args after `--sftp <alias>`
  - preserves `<alias> sftp` as a remote SSH command
  - preserves upload/download parsing
- Command-plan tests:
  - direct interactive SFTP command has no `-b`
  - tunnel interactive SFTP includes generated `ProxyCommand`
  - strict host-key options match existing SFTP behavior
  - secret env does not expose passwords or MFA in argv
- Relay rejection tests:
  - nested relay target fails before `execve`
  - localized error string is present
- Preview tests:
  - `--print-command --sftp <alias>` prints no secrets
  - no temporary batch file is created
- Expect/fake binary tests:
  - agent/no-prompt path reaches `sftp>` and calls `interact`
  - password prompt path
  - MFA prompt path
  - host-key prompt path
  - EOF before `sftp>` fails cleanly
  - timeout before `sftp>` fails cleanly
  - terminal echo is restored on cleanup
  - spawned command omits batch mode
- Regression tests:
  - existing upload/download batch-mode tests still pass
  - relay transfer tests still pass

Manual smoke when available:

- direct password interactive SFTP
- direct key/passphrase interactive SFTP
- tunnel interactive SFTP through a jump host
- one MFA-protected interactive SFTP path

## Tradeoffs

### Benefits

- Covers ad-hoc remote exploration without turning sshgo into a file manager.
- Reuses existing host resolution, authentication, jump-host, and audit-start behavior.
- Keeps the common upload/download workflow fast and explicit.
- Avoids new dependencies and avoids building a custom SFTP protocol layer.

### Costs And Risks

- The audit trail can only say that an interactive SFTP session started.
- Users can perform many operations inside `sftp>` that sshgo cannot validate or summarize.
- Expect branching may become harder to maintain if interactive and batch behavior share too much script code.
- Manual smoke is important because interactive prompt behavior depends on OpenSSH and terminal behavior.

## Open Questions

1. Should the command be `sshgo <alias> sftp` or `sshgo --sftp <alias>`?
   - Decision: use `sshgo --sftp <alias>`. The positional form already means "run remote command `sftp`" and must not be repurposed.
2. Should TUI expose this as a visible action?
   - Decision: not in the first version. Keep CLI-only until real usage proves it belongs in the common TUI flow.
3. Should interactive SFTP use `sftp_login.exp` or a separate script?
   - Decision: reuse `sftp_login.exp`. The shared authentication flow stays small; interactive mode only changes command construction, batch-file lifecycle, and the first `sftp>` prompt handoff.

## Review Status

- status: reviewed
- verdict: PASS
- notes: Implemented as a CLI-only `--sftp <alias>` entry point. Existing upload/download batch mode remains unchanged; `sshgo <alias> sftp` remains a remote SSH command shortcut; relay is rejected before Expect handoff.
