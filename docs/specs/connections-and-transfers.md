# Connections And Transfers

## Metadata

- slug: connections-and-transfers
- status: approved
- owner: PM/Architect/Engineer
- related_roadmap: docs/roadmap.md

## Scope

This spec owns current SSH, SFTP, relay, authentication, host-key, proxy, and
terminal-title behavior. It replaces completed connection, security, jump-mode,
proxy, SFTP, and terminal-title implementation plans.

## Process And Authentication Model

Python resolves config, builds a `CommandPlan`, optionally emits a terminal title,
records a launch audit event, and replaces itself with an Expect script through
`os.execve()`. Expect owns interactive prompt handling and spawns OpenSSH tools.
Python does not supervise the live session.

Passwords and MFA secrets exist only in the environment copy passed to Expect:

```text
SSHGO_TARGET_PASS
SSHGO_JUMPER_PASS
SSHGO_MFA_SECRET
SSHGO_JUMPER_MFA_SECRET
```

Expect reads and removes those values before spawning OpenSSH. TOTP codes are
generated only when a matching MFA prompt arrives. Secrets never appear in argv,
previews, titles, or audit command fields.

Target and jump authentication are independent. Direct and shell-jump flows know
the active stage explicitly. Tunnel prompts are classified from bounded user/host
or identity-file tokens; automatic response occurs only when exactly one hop
matches. Equal endpoints, overlapping hostnames, or equal/prefix-colliding key paths
are ambiguous and fall back to manual input without consuming either stored secret.

Expect argument parsers consume recognized option/value pairs. Option-shaped values
remain values; unknown options and missing values fail before secrets are read or a
child process is spawned.

## Host-key Policy

`strict_host_key_checking=true` is the default and maps to OpenSSH
`StrictHostKeyChecking=accept-new` with the user's normal known-hosts files.
`false` enables the explicit loose compatibility mode using
`StrictHostKeyChecking=no` and `UserKnownHostsFile=/dev/null`.

In local/tunnel flows, target host keys belong to the local environment. In
`shell` and `relay`, target host-key prompts occur on the jump host. Relay target
commands inherit the configured policy.

## ProxyCommand

A direct host or a non-nested parent jump host may define a trusted OpenSSH
`proxy_command`. It applies to direct SSH, initial remote commands, direct SFTP,
interactive SFTP, or the first local hop to that parent. A nested target, including
a nested intermediate host with children, cannot define its own `proxy_command`.

sshgo expands only documented `{{name}}` placeholders and leaves OpenSSH `%h` and
`%p` intact. Generated tunnel proxy commands escape parent-proxy `%` tokens so the
inner OpenSSH process receives them. OpenSSH executes `ProxyCommand` locally; sshgo
does not parse shell content, expand environment variables, inject secrets, or import
the field from `~/.ssh/config`.

## Jump Modes

Effective mode priority is:

```text
target host > parent jump host > global config > built-in default
```

Built-in defaults are `ssh_jump_mode=shell` and
`transfer_jump_mode=tunnel`.

| Operation | Mode | Mechanism | Jump TCP forwarding |
|---|---|---|---|
| SSH | `shell` | Login to parent, then run target SSH from its shell | not required |
| SSH | `tunnel` | Local OpenSSH reaches target through generated `ssh -W` proxy | required |
| Upload/download | `tunnel` | Local OpenSSH SFTP through generated proxy | required |
| Upload/download | `relay` | Copy through a temporary path on the parent | not required |

Only a direct-parent host topology is supported. sshgo does not auto-detect,
auto-fallback, or expose a per-command mode override. Validation rejects unknown
mode values, relay on a non-nested host, a non-absolute `relay_temp_dir`, and a
negative/non-integer `relay_transfer_timeout`.

Authentication location differs by mode:

- Direct and tunnel target authentication runs locally; local key paths, agent,
  and known-hosts state apply.
- In `shell` and `relay`, target authentication runs from the parent environment;
  target `id_file` is a parent-side path and explicit `use_ssh_agent=true` means the
  parent-side agent.
- Global `config.use_ssh_agent` applies to direct hosts and tunnel targets. It does
  not silently opt a shell/relay target into the parent agent.

## SSH

`ssh_jump_mode=shell` logs into the parent, waits for an interactive prompt, starts
target SSH, and then interacts with the target. This supports parents that disable
TCP forwarding. `tunnel` keeps the target OpenSSH process local and is preferred when
local agent, keys, or known-hosts state must apply.

Interactive SSH recognizes common shell prompt glyphs. After target authentication,
a prompt-detection timeout without an initial command hands control to the user
instead of declaring the session failed. Initial-command execution still requires a
recognized prompt so sshgo knows when to send the command.

An initial positional command is sent after login and the session remains
interactive. It is not a non-interactive command runner and does not return the
remote command's exit status.

## Direct And Tunnel SFTP

The upload/download shortcuts transfer one regular file. Direct and tunnel flows use
OpenSSH `sftp -b` with a private temporary batch file containing exactly one quoted
`put` or `get`. The subprocess exit status, not localized output text, determines
success. Cleanup removes the batch file on success, failure, signal, or spawn error.
Creation also prunes sshgo batch files older than the retention threshold so a crash
does not leave temporary command files indefinitely.

OpenSSH batch mode normally forces `BatchMode=yes`, which would disable password,
passphrase, and keyboard-interactive prompts. `sftp_ssh_wrapper.py` removes only that
implicit value, prepends `BatchMode=no`, preserves the remaining SSH arguments, and
execs the system `ssh`; Expect continues to answer supported prompts.

Direct/tunnel paths containing newline, carriage return, double quote, or backslash
are rejected before handoff because they cannot be represented safely in the current
batch command. `--print-command` creates no batch file and may show only a sanitized
one-line transfer preview.

`--sftp <alias>` opens a normal interactive `sftp>` prompt for direct hosts and
nested tunnel hosts. It does not use `-b` or the wrapper. Relay targets are rejected
before handoff. The positional form `<alias> sftp` remains an SSH initial command.

## Relay Transfer

Relay is an explicit two-copy fallback for parents that disable TCP forwarding:

```text
upload:   local -> parent temporary file -> target -> cleanup
download: target -> parent temporary file -> local -> cleanup
```

It is not SFTP and may leave file content temporarily on the parent. It supports
regular files only. Paths are quoted for remote shell/scp use; safe local-parent
staging prefers interactive SFTP and falls back to scp only when the SFTP subsystem
is unavailable. Scp changes protocol only for protocol-option incompatibility, not
for authentication, permission, or path errors.

Each copy phase is visible. Internal status markers and housekeeping commands are
not printed. Failure paths attempt cleanup; cleanup failure warns without replacing
the original transfer result. Login, directory preparation, and cleanup use short
command timeouts. File-copy phases use `config.relay_transfer_timeout` (default
`1800`; `0` disables the Expect transfer timeout).

## Terminal Titles

Titles are disabled by default. When enabled, `ConnectionRuntime` emits a best-effort
OSC title immediately before audit start and handoff for SSH, interactive SFTP,
upload/download, and relay. Config fields are:

| Field | Values | Default |
|---|---|---|
| `terminal_title_enabled` | boolean | `false` |
| `terminal_title_target` | `tab`, `window`, `both` | `tab` |
| `terminal_title_format` | `alias`, `host`, `alias_host` | `alias_host` |
| `terminal_title_scope` | `auto`, `always` | `auto` |

Titles contain only action, alias, and resolved endpoint; control characters,
secrets, commands, and paths are excluded. Default port `22` is hidden. `auto` emits
only for recognized terminal contexts; Ghostty's tab target uses its compatible
window-title sequence. Output failure never blocks a connection, and the previous
title is not restored because Python no longer owns the session.

## Audit Boundary

Python records start and exec-failure events for SSH, interactive SFTP, SFTP
transfers, and relay. Relay's final transfer/cleanup result is terminal output from
Expect. Final exit status, duration, remote command result, paths typed in `sftp>`,
and interactive commands are unavailable after `execve`.

## Non-goals

- No Python SSH/SFTP implementation or live-session supervision.
- No deeper multi-hop chain, automatic mode detection, or automatic relay/tunnel
  fallback.
- No directory or multi-file batch transfer.
- No target `ProxyCommand` stacking, full SSH config parsing, or untrusted command
  expansion.
- No per-host terminal-title templates or title restoration.

## Acceptance Criteria

1. Every connection mode keeps secrets out of argv and routes automatic responses
   only to an unambiguous authentication stage.
2. Direct, shell, tunnel, batch SFTP, interactive SFTP, and relay retain their
   documented execution and authentication environments.
3. Proxy and placeholder validation rejects conflicting or unresolved plans before
   network handoff.
4. SFTP success follows process exit status; batch files and relay temporary files
   follow their cleanup contracts.
5. Preview remains side-effect-free; preview, title, and audit content remain
   secret-free.

## Review Status

- status: reviewed
- verdict: PASS_WITH_RISKS
- notes: Automated coverage exercises command construction, fake prompt routing,
  SFTP batch lifecycle, and relay fallback. Real password/passphrase/MFA/tunnel
  prompt variants remain a manual-smoke residual when these paths change.
