# Connections And Transfers

## Metadata

- slug: connections-and-transfers
- status: approved
- last_updated: 2026-10-12
- related_roadmap: docs/roadmap.md

## Scope

This spec owns current SSH, SFTP, relay, authentication, host-key, proxy, and
terminal-title behavior.

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

Interactive SSH recognizes common shell prompt glyphs plus the bracketed-paste enable
sequence that zsh and readline emit immediately before reading input. Rich prompts
(for example Starship, where right-side text and cursor escapes follow the glyph) are
detected through that sequence instead of waiting for the prompt-detection timeout.
After target authentication, a prompt-detection timeout without an initial command
hands control to the user instead of declaring the session failed, and that fallback
ends with success once the interactive session closes. Initial-command execution
still requires a recognized prompt so sshgo knows when to send the command.

An initial positional command is sent after login and the session remains
interactive. It is not a non-interactive command runner and does not return the
remote command's exit status.

## Direct And Tunnel SFTP

The upload/download shortcuts transfer one regular file. Direct and tunnel flows use
OpenSSH `sftp -b` with a private temporary batch file containing exactly one quoted
`put` or `get`. The subprocess exit status, not localized output text, determines
success. Cleanup removes the batch file on success, failure, signal, or spawn error.
A native `progress` command precedes the single copy command in the batch file,
enabling OpenSSH's own terminal progress meter for standalone and session-shortcut
SFTP. No custom polling/progress engine or newer command-line flag is required.
Very small files may show only the final 100% line.
Creation also prunes sshgo batch files older than the retention threshold so a crash
does not leave temporary command files indefinitely.

Authentication/prompt discovery has a 20-second Expect timeout. Once the batch
`sftp>` command prompt is seen, Expect imposes no copy-duration/output-silence
deadline: large batch transfers can be silent while progressing. OpenSSH errors,
process exit status and user cancellation still apply. This is shared by standalone
and reused-session SFTP; relay keeps its separate configured transfer timeout.

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

## Remote Shell File Shortcuts

Opt-in session shortcuts automatically define temporary `sget`/`sput` functions in
ordinary interactive sh/dash, bash and zsh. A target SSH exec request creates a private
0700 `/tmp/sg-init-<session>` directory and 0600 text startup files. No user profile
is modified and no remote binary is installed. The supervising shell removes its
known files on normal exit or handled HUP/TERM; SIGKILL/network loss may leave residue.
The functions use only shell builtins for byte-preserving UTF-8 hex encoding,
including Bash 3.2; no `od`, `tr` or `hexdump` is required. Encoding confines the C
locale and scratch variables to a subshell and normalizes signed Bash byte values.
It does not start an external process per byte or change the interactive locale.

Bash uses a private rcfile that sources `/etc/profile` and the first readable user
login profile; sh/dash use a private ENV file that sources `/etc/profile`, `.profile`
and the user's ENV file. These are interactive shells with explicitly loaded login
profiles, not native login-shell flag semantics. Zsh uses only a temporary `.zshenv`, restores the user's ZDOTDIR before normal
profile/rc processing, and defines functions via a one-shot precmd hook. This avoids
redirecting system-configured history/session files into the temporary directory.
Existing names are not overwritten. Startup scripts that exec another program,
disable rc loading or change startup selection are outside automatic-init guarantees.
The caller's umask is restored before user startup files run.

Only the session's random READY handshake followed by a successful reused-channel
probe enables requests. Startup information is printed before SSH starts; successful
probing does not print over the remote prompt or consume typed input. Failures still
produce a notice. Failed probes also show a bounded diagnostic with control
characters escaped (at most 1024 displayed characters); successful probe output
remains hidden. Channel errors and probe timeouts are distinguished.
Prompt glyphs and command echo are not readiness proof.
No target initialization program is typed into the terminal, including ForceCommand
menus. Missing tools, name conflicts, unavailable channels and timeout disable only
the shortcut. Input remains ordinary SSH; there is no manual init shortcut.

| SSH / transfer combination | Shortcut transport |
|---|---|
| direct / SFTP | Existing SFTP runner through the local private target master |
| tunnel / SFTP | Same, with the initial target connection using its planned tunnel |
| shell / SFTP | Local SFTP through a byte-transparent exec bridge: local master A to jump, jump master B to target subsystem |
| shell / relay | Existing relay runner with both A and B injected into staging, copying and cleanup |
| tunnel / relay | Unavailable; no new authentication path or automatic mode change |

The shell/SFTP bridge does not require jump TCP forwarding or a jump SFTP client.
It requires exec channels on the jump, its existing `ssh`/`false`, and the target
SFTP subsystem. Relay retains its existing staging, scoped fallback and cleanup
policy and requires existing SCP support. Restricted/menu-only bastions are not
promised to work. Standalone transfer/interactive SFTP modes are unchanged.

Each initial connection uses a private ControlPath, ControlMaster=yes and finite
ControlPersist=30. The foreground mux client's lifetime remains independent of an
active transfer channel. Every later SFTP, exec, probe and cleanup command uses
`-F /dev/null`, ControlMaster=no, ControlPersist=no, BatchMode=yes, no original
credentials/proxy, and an absolute trusted `false` ProxyCommand. Missing or rejected
masters therefore fail closed, including a disconnect after precheck, without new
authentication. Tool paths come from standard system directories. Initial authentication remains the ordinary login flow. With session shortcuts,
the initial shell-mode target also inherits the configured host-key policy; its
known-hosts storage remains on the jump host.

Manual authentication monitors both keyboard input and the SSH channel. SSH/terminal
EOF, cancellation or a 120-second per-prompt deadline restores terminal state and
uses normal session cleanup; remote output or partial typing does not reset the deadline.
Asynchronous completion (for example, push MFA) returns READY, initialization failure,
shell readiness and login-error events to the main login state machine without
consuming them or requiring Enter. Fragmented events remain in Expect's buffer.

`login.exp` owns keyboard routing, bounded terminal metadata parsing, one pending
request and one helper. Each transfer requires local confirmation; remote output is
not an authorization source. Session IDs prevent accidental cross-session matches,
not malicious requests by the remote user. Old/busy requests are dropped. Frames
are bounded to 17000 characters and paths to 4096 UTF-8 bytes. Local displays escape
control characters. File bytes never traverse the terminal metadata parser.

In shell mode, the long target launcher is written as a 0600 text file in the
private jump directory over master A's exec channel. Only its short `/bin/sh` launch
command enters the jump terminal, avoiding canonical/line-editor input limits.
A wrapper launch marker separates command echo from subsequent target authentication
and prompt matching. The launch file is removed with that session's jump resources. On target foreground exit it emits a
session-bound closed
frame, disables shortcuts, cancels the helper and cleans B through A; the jump shell
remains usable. Outer EOF or HUP/TERM cancels the helper then closes private masters
and contexts. Helpers receive TERM with a two-second grace before forced stop;
cleanup is bounded and best effort. Ctrl+C/Esc cancels just the local operation.
No successful copy is inferred from function return codes or partial relay phases.

Normal cleanup is proactive; the 30-second ControlPersist limit is only an idle
fallback. Network failure, lost close frames, SIGKILL or stuck remote copy channels
cannot guarantee immediate remote cleanup. Unconfirmed known resources are reported
for inspection, not scanned/deleted broadly. No cleanup reconnects to authenticate.

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

`login.exp` does not capture the SSH child's exit status, so `sshgo <alias>`
(including `sshgo <alias> <command>`) exits 0 on its normal paths even when the
remote command fails; only Expect-side failures use a non-zero exit. Recording or
propagating the real status would require new Expect work and is deferred.

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
