# CLI And TUI

## Metadata

- slug: cli-and-tui
- status: approved
- last_updated: 2026-10-12
- related_roadmap: docs/roadmap.md

## Scope

This spec owns the current command-line safety, diagnostics, and curses interaction
contracts.

## CLI Shortcuts

`sshgo <alias>` prefers an exact host alias. Without an exact match, one unique
prefix is accepted; multiple prefixes fail before any connection and list the
candidates. Unknown aliases and locally invalid connection plans also fail safely.

Supported shortcut shapes are:

```text
sshgo <alias>
sshgo <alias> <initial-command...>
sshgo <alias> upload <local> <remote>
sshgo <alias> download <remote> <local>
sshgo --sftp <alias>
```

Initial command arguments are shell-joined to preserve boundaries, sent after an
interactive login, and followed by normal interaction. Upload/download support one
file. `--sftp` is the only interactive SFTP entry point; `<alias> sftp` remains an
initial SSH command.

Unsupported deeper-than-direct jump topology is rejected by config validation and
again by runtime planning.

## Session Shortcut Interaction

`--session-shortcuts` and `--no-session-shortcuts` are mutually exclusive per-run
overrides of global OR target-node `session_shortcuts_enabled` (both default false);
options precede the alias. Without an alias they apply to TUI Enter via the same planner. Explicit enable
requires interactive stdin/stdout and rejects initial commands, upload/download and
`--sftp`. Read-only `--print-command` creates no context or socket. With config/node
enable, noninteractive launches and unavailable combinations retain ordinary SSH
with a notice. TUI details report planned availability, not a proven live capability.

Supported target shells initialize automatically through private text startup files.
One informational line is printed before SSH starts. The READY handshake and channel
probe complete silently, leaving the remote prompt intact; no extra Enter or Ctrl+]
sequence is needed. Input typed during the startup probe remains queued for the shell.
Only actual transfer prompts take exclusive keyboard input and drain pending keys. Initialization never sends a script to a foreground menu/editor.
The endpoint and authenticated identity are frozen at login and do not follow manual
nested SSH, `su` or another shell. Local relative paths and default downloads use the
cwd where this session launched sshgo, never the wrapper/script installation directory.

- `sget <remote-file> [local-destination]` uses remote PWD for relative source paths;
  local paths resolve against the local launch directory, with local tilde expansion.
  Default local destination is the source basename. An existing local directory gets
  that basename appended.
- `sput [local-file] [remote-destination]` prompts locally when source is omitted.
  It uploads one existing regular file to remote PWD by default. An explicit trailing
  slash destination appends the local basename; other destinations are literal.
- Each request shows both endpoints. New downloads accept Enter/y; existing local
  destinations and uploads (remote existence unknown) require `y`, default cancel.
  Quote local `~` arguments to prevent remote shell expansion.
- NUL, CR/LF, double quotes, backslash and wildcard syntax are rejected, consistent
  with the restricted batch adapter. No directory, multi-file or shell execution
  request is accepted. Shell functions return request emission status only.
- During the local operation, keyboard input is exclusive to its helper; stale
  pending input is drained before confirmation. Remote logs are drained into a
  bounded buffer starting immediately after the request frame. The transfer result
  (or cancellation/failure) is printed before replaying that output and the remote
  prompt, so no extra Enter is needed. Overflow is reported before replay. Esc/Ctrl+C cancels
  this operation, then terminal mode and input return to SSH.

## Read-only And Recovery Commands

- `--validate` validates the selected raw config without saving or initializing
  mutable/runtime services.
- `--history` reads runtime JSONL history and supports limit/filter without creating
  a missing runtime directory.
- `--print-command` supports SSH, initial command, upload/download, and interactive
  SFTP shapes. It prints the resolved local handoff using shell-safe quoting, creates
  no transfer batch file, audits nothing, emits no title, and exposes no secret
  environment values.
- `--doctor` reports compact PASS/WARN/FAIL lines for config path and validity,
  Expect/OpenSSH availability, bundled script presence/executability, runtime data
  writability and permissions, config/backup permissions, SSH agent state, host-key
  mode, terminal capabilities, and screen policy. Required failures produce a
  non-zero exit.
- `--list-backups` and `--restore-backup INDEX` operate on the resolved config path;
  restore is explicit and validates the selected backup.

These commands use the same config-path priority as normal startup. Preview,
validation, and history remain side-effect-free; doctor may perform bounded local
writability probes.

## TUI Navigation And Layout

The TUI remains keyboard-first:

| Keys | Behavior |
|---|---|
| arrows or `j`/`k` | Move selection |
| Enter | Connect to a host or toggle a group |
| `h`/`l` | Collapse/expand |
| `a`/`e`/`d` | Add/edit/delete |
| `f` | Search |
| Esc | Cancel the current mode/action |
| `q` | Quit |

Main list, forms, messages, details, and footer use a shared visual shell. Wide
terminals show list and resolved details side-by-side without overwriting rows. The
Recent group lists up to ten most recent distinct hosts, resolving each entry to the
current node and falling back to a read-only history snapshot; it is hidden when
Recent is disabled or empty. Printable Unicode is accepted in search and form fields;
ellipsizing, viewports, and cursor placement use terminal cell width rather than raw
character count.

## Forms And CRUD

Host forms group Basic, Auth, and Advanced fields. Advanced fields are collapsed for
new hosts and opened when editing a node that already uses them. Field visibility
tracks auth, proxy, and jump context.

Before add or edit writes config, the TUI validates an in-memory candidate in the
current tree. Errors stay inside the form, preserve typed values, and focus a likely
field when possible. No failed candidate is written or assigned a permanent ID.

Parent selection offers top level plus saved editable hosts/groups only. Recent,
SSH-config imports, and other generated/read-only nodes cannot become persistence
parents. Delete confirmation defaults to Cancel and summarizes group descendants.

Text and password editors support cursor movement, Home/End, Ctrl+A/Ctrl+E,
Backspace/Delete, Ctrl+U, paste-friendly printable insertion, Enter commit, and Esc
cancel. Password fields share the same editing behavior while masking display.

The detail pane shows resolved target, authentication method, jump host and modes,
host-key context, and proxy command where applicable. It never renders saved password
or MFA values.

## Screen Policy

`config.tui_screen_policy` accepts:

| Policy | Behavior |
|---|---|
| `isolated` | Default; use curses alternate screen, restore the normal screen, and preserve scrollback |
| `private` | Restore first, then attempt to clear the visible screen and current terminal scrollback |

`restore_screen()` is idempotent and runs on quit and before connection handoff.
When terminfo lacks alternate-screen support, sshgo clears the current curses screen
to reduce residue and doctor warns. `private` is opt-in because it affects the whole
terminal session, not only sshgo output. Terminal-specific alternate-screen retention
cannot be repaired portably by the application.

## Implementation Boundaries

- `Tui` owns curses lifecycle, windows, navigation state, form loops, and high-level
  flows.
- `tui_render.py`, `tui_recent.py`, `tui_flows.py`, `tui_text.py`, and
  `tui_forms.py` own focused rendering, Recent, CRUD, text, and form helpers.
- TUI work must not change SSH/SFTP/relay planning or introduce a GUI/web layer.
- UI strings go through `i18n` with aligned English and Chinese entries.

## Non-goals

- No mouse UI, remote file browser, tags/favorites, health dashboard, or multi-host
  orchestration.
- No silent alias guess, network reachability probe in doctor, or secret-bearing
  preview.
- No inline curses policy or selective removal of TUI frames from scrollback.
- No stateful TUI class split solely to reduce line count.

## Acceptance Criteria

1. Exact/unique aliases remain fast while ambiguity and unsupported topology fail
   before network handoff.
2. Read-only commands remain concise, actionable, and secret-safe.
3. TUI CRUD validates before persistence and excludes generated nodes from editable
   parent selection.
4. Unicode editing, resolved details, deletion safety, and screen restoration retain
   focused test coverage.
5. Default screen behavior preserves scrollback; destructive cleanup remains opt-in.
