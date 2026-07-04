# Agent Guide

This file provides repository guidance for coding agents and maintainers working on sshgo. Keep it focused on stable project facts, local workflows, architecture boundaries, and verification commands.

## Project Overview

**sshgo** is a TUI-based SSH connection manager written in Python 3 (stdlib only, no external Python dependencies). It manages hosts/groups via a JSON config file, supports password/key/MFA authentication, nested jump hosts, and `~/.ssh/config` import.

## Quick Reference

| Action | Command |
|--------|---------|
| Run TUI | `./sshgo.sh` or `~/.venv/bin/python sshgo.py` |
| Connect to host | `./sshgo.sh <alias>` |
| Run remote command | `./sshgo.sh <alias> ls -la` |
| Upload file | `./sshgo.sh <alias> upload <local> <remote>` |
| Download file | `./sshgo.sh <alias> download <remote> <local>` |
| Open interactive SFTP | `./sshgo.sh --sftp <alias>` |
| Preview command | `./sshgo.sh --print-command <alias>` |
| Run diagnostics | `./sshgo.sh --doctor` |
| Toggle encryption | `./sshgo.sh --toggle-encryption` |
| Toggle language | `./sshgo.sh --toggle-language` |
| Toggle detail pane | `./sshgo.sh --toggle-details` |
| Use alternate config | `./sshgo.sh -e /path/to/hosts.json` |

**Dependencies**: No Python pip packages needed. Runtime shell tools must include `expect` plus OpenSSH client commands (`ssh`, `sftp`, `scp`).

## Agent Workflow

- Read existing code and docs before editing. Prefer the current stdlib-only Python style and avoid adding package dependencies.
- Keep changes scoped to the requested behavior. Do not mix unrelated refactors, feature work, or formatting churn into the same change.
- Treat `hosts.json`, `.venv/`, and local dot-directories as local environment/configuration unless explicitly asked to modify them.
- Do not change accepted behavior that is documented in `docs/specs/*.md` without updating the matching spec documentation.
- If a requested change conflicts with documented non-goals or accepted specs, surface the conflict before implementation.
- Preserve the Expect handoff model unless a spec explicitly changes it. Python records start/exec-failure audit events and then uses `execve`; it does not supervise live SSH/SFTP sessions.
- Keep common workflows highly polished: exact alias shortcuts should be fast, ambiguous aliases must fail before connecting, and diagnostic output should be concise and actionable.
- Run the narrowest meaningful verification before delivery and report anything not run.

## Architecture

### Module Layout

| File | Responsibility |
|------|---------------|
| `sshgo.py` | Entry point: arg parsing, config path resolution, dispatches to TUI or shortcut commands |
| `sshgo.sh` | Thin shell wrapper that resolves `sshgo.py` by script path while preserving the caller's current working directory |
| `host_manager.py` | `HostManager` class — public facade for config lifecycle, stable node ID assignment, credential encryption/decryption, CRUD, validation delegation, alias lookup, and compatibility wrappers for connection preview/execution |
| `connection_errors.py` | Shared connection/config runtime exceptions kept import-compatible through `host_manager.py` |
| `connection_plan.py` | `CommandPlan` plus secret environment mapping and UTF-8 locale normalization for Expect handoff |
| `connection_planner.py` | SSH, SFTP, interactive SFTP, and relay command-plan builders; consumes `HostManager` through a narrow structural adapter and must not import `host_manager.py` |
| `connection_runtime.py` | Executes `CommandPlan` objects: executable checks, optional terminal title, audit start/failure records, environment construction, and `os.execve()` handoff |
| `host_tree.py` | Pure host/group tree helpers — traversal, lookup, replacement, parent/index lookup, potential parent listing, node ID assignment, and runtime parent-link rebuilding |
| `config_store.py` | `ConfigStore` plus JSONC parser — reads `hosts.json`, fingerprints loaded files, writes JSON atomically with optional stale-write detection, rotates/list/restores backups, and preserves JSONC comments/trailing-comma read support |
| `config_validation.py` | Pure parsed-config validation helpers — validates top-level config, placeholders, host/group nodes, jump modes, relay temp paths, and keeps a compatibility export through `host_manager.py` |
| `audit_logger.py` | `AuditLogger` class — manages runtime data dir (`~/.sshgo/` or `$SSHGO_DATA_DIR`), writes audit logs in JSONL format with node identity/endpoint fields and retention limits (history: 1000, audit-simple: 5000, audit-full: 2000) |
| `tui.py` | `Tui` class — curses-based interactive interface (tree view, search, add/edit/delete forms, detail preview pane) |
| `config_parser.py` | `SshConfigParser` — parses `~/.ssh/config` into sshgo host nodes |
| `terminal_title.py` | Optional terminal tab/window title formatting, terminal compatibility detection, and OSC escape emission before SSH/SFTP/transfer handoff |
| `crypto.py` | PBKDF2-HMAC-SHA256 key derivation plus HMAC-authenticated stdlib stream encryption for optional credential encryption; legacy XOR+Base64 ciphertext remains readable |
| `auth.py` | TOTP/HOTP generation from Base32 secrets (for MFA/2FA) |
| `i18n.py` | Simple English/Chinese string localization (`I18N` class, global `i18n` instance) |
| `login.exp` | Expect script that handles interactive SSH login (password, passphrase, prompt-time MFA generation, jump host chaining) |
| `sftp_login.exp` | Expect script for direct/tunnel SFTP file transfer (upload/download) and CLI-only interactive SFTP sessions with same authentication logic as login.exp |
| `sftp_ssh_wrapper.py` | Small stdlib-only ssh wrapper used by `sftp_login.exp` batch mode to remove OpenSSH `sftp -b`'s implicit `BatchMode=yes` while preserving all other ssh args |
| `relay_transfer.exp` | Expect script for non-SFTP relay file transfer through a jump host using temporary jump-host storage and `scp` |
| `hosts.json` | Project fallback config file: `{"config": {...}, "hosts": [...]}` with `group` and `host` nodes |

### Config Format Support

- **JSONC** (`hosts.json`): The only supported configuration format.
- Supports `//` and `#` single-line comments plus trailing commas.
- TOML and YAML are intentionally not supported to avoid Python package dependencies or project-maintained serializers.

### Key Flows

1. **Startup**: `sshgo.sh` → `sshgo.py:main()` → resolve config path (CLI arg > env var > `~/.config/sshgo/hosts.json` when present > default `hosts.json`) → `HostManager` delegates JSONC config read to `ConfigStore`, assigns missing saved-node IDs in memory, and optionally imports `~/.ssh/config` → non-read-only CLI paths explicitly persist pending saved-node ID migration → dispatch to TUI or shortcut handler.

2. **TUI**: `Tui.run()` enters curses main loop — render tree, handle keyboard input (j/k navigation, a/e/d CRUD, f search, h/l fold/unfold, q quit), forms for add/edit.

3. **SSH Connection**: `HostManager.execute_interactive_connection()` delegates launch construction to `ConnectionPlanner`, then `ConnectionRuntime` stores password/MFA secrets only in the `SSHGO_*` environment copy, optionally emits a terminal title through `terminal_title.py`, records a `started` audit event, and uses `os.execve()` to replace Python with `login.exp`. Target and jump host auth are computed independently. Hosts can use a custom `proxy_command`; when such a host is used as a jump-host parent, child connections use the parent `proxy_command` for the first hop. Nested interactive SSH supports `ssh_jump_mode=shell` (default, login to jump then run target SSH from the jump shell) and `ssh_jump_mode=tunnel` (OpenSSH `ProxyCommand` / `ssh -W`). Python does not wait for the SSH session and cannot record final duration, exit code, or restore a previous terminal title.

4. **File Transfer**: `execute_file_transfer()` keeps the public shortcut path but delegates mode-specific plan construction to `ConnectionPlanner`. `tunnel` (default) uses true local SFTP via `sftp_login.exp`, runs a single `put/get` through OpenSSH `sftp -b`, and requires jump-host TCP forwarding; nested tunnel mode receives a Python-generated `-tunnel-proxy-command`, including any parent jump-host key/proxy options. Because OpenSSH `sftp -b` injects `BatchMode=yes`, `sftp_login.exp` launches SFTP with `-S sftp_ssh_wrapper.py` so password/passphrase/MFA prompts keep working. `sshgo --sftp <alias>` opens a standard interactive `sftp>` prompt for direct/tunnel hosts through the same Expect auth flow, but does not use `sftp -b` or `sftp_ssh_wrapper.py`; `sshgo <alias> sftp` remains a remote SSH command. `relay` uses `relay_transfer.exp`, copies regular files through a temporary path on the jump host with `scp`, retries local-to-jump scp with legacy protocol only for protocol-incompatibility failures, is not SFTP, and reports final transfer/cleanup status in Expect output rather than Python audit. Interactive SFTP rejects relay before Expect handoff.

5. **Recent Resolution**: TUI builds the Recent group from audit history. It resolves current nodes by `node_id` first, then legacy name/endpoint fields, and only falls back to read-only history snapshots when the configured node no longer exists.

6. **Encryption**: Toggle via `--toggle-encryption`. Uses PBKDF2 (260k iterations) with an HMAC-authenticated stdlib stream format for new ciphertext, while preserving legacy XOR+Base64 read compatibility. Master password is prompted interactively and never stored.

### Node Types in `hosts.json`

- **group**: `{"id": "...", "type": "group", "name": "...", "expanded": bool, "children": [...]}`
- **host**: `{"id": "...", "type": "host", "name": "...", "host": "addr:port", "user": "...", "password": "...", "id_file": "...", "mfa_secret": "...", "proxy_command": "OpenSSH ProxyCommand", "ssh_jump_mode": "shell|tunnel", "transfer_jump_mode": "tunnel|relay", "children": [...]}` — `children` on a host makes it a jump host. `proxy_command` is supported on direct hosts and non-nested parent jump hosts only; nested target hosts, including nested intermediate hosts that also have children, must not define their own `proxy_command`. `id` is managed by sshgo and should be preserved across edits. Global `config.placeholders` can be referenced as `{{name}}` in `host`, `user`, `id_file`, `proxy_command`, and `relay_temp_dir`.

### Config Priority

1. `--extra-config <path>` CLI argument
2. `SSHGO_CONFIG_PATH` environment variable
3. `~/.config/sshgo/hosts.json` when present
4. Default `hosts.json` next to script

### Documentation Layers

- `docs/vision.md`: product goals and non-goals.
- `docs/roadmap.md`: completed milestones and exit criteria.
- `docs/gap-analysis.md`: current risks, closed gaps, optimization outcomes, and future candidate boundaries.
- `docs/specs/*.md`: accepted behavior and implementation boundaries.
- `docs/specs/jump-host-connection-modes.md`: configurable SSH/transfer jump modes (`shell`, `tunnel`, `relay`).
- `docs/specs/custom-proxy-command.md`: host-level custom `proxy_command`, parent jump-host proxy, and `config.placeholders` behavior.
- Verification commands live in this file; avoid adding separate per-spec test-plan status files.

## Development Notes

- **Python**: Uses only stdlib modules (`curses`, `json`, `argparse`, `getpass`, `hmac`, `hashlib`, `base64`, `struct`, `shlex`, `curses.textpad`). Run with `~/.venv/bin/python` per project rules.
- **External tools**: `expect` is required for interactive prompt handling, and OpenSSH client commands (`ssh`, `sftp`, `scp`) must be available for connections and transfers.
- **Expect scripts**: `login.exp`, `sftp_login.exp`, and `relay_transfer.exp` must be executable (`chmod +x`). HostManager ensures this before shortcut `execve`. `sftp_ssh_wrapper.py` must also remain executable so OpenSSH `sftp -S` can launch it.
- **MFA generation**: Expect scripts generate TOTP codes when an MFA prompt arrives by invoking `auth.py` with the secret from the transient `SSHGO_*` environment copy. Secrets are not passed in argv.
- **Process handoff**: Shortcut connections, transfers, and interactive SFTP sessions replace Python via `os.execve()` from `ConnectionRuntime`. The Python manager records start/exec failure events only; it does not supervise the live SSH/SFTP session.
- **Terminal titles**: `config.terminal_title_enabled=false` by default. When enabled, `ConnectionRuntime` calls `terminal_title.emit_terminal_title()` immediately before audit start and `execve` for SSH, interactive SFTP, SFTP transfer, or relay transfer. Title output uses best-effort OSC sequences only, never includes secrets or transfer paths, and is not restored after the remote session exits.
- **Audit logging**: JSONL files in `~/.sshgo/`. History and audit-simple are always written for SSH and SFTP starts, including `sftp_interactive_started`; audit-full requires `--audit-full` flag. New records include `node_id`, `port`, and `endpoint`. Because of the execve handoff, final duration, exit code, and commands typed inside `sftp>` are not available in current audit records.
- **Config saves**: `ConfigStore` writes JSON atomically and keeps best-effort backups at `hosts.json.bak`, `hosts.json.bak.1`, and `hosts.json.bak.2`; `HostManager` delegates save/backup operations to it. `HostManager` saves pass the loaded file fingerprint so a stale instance fails instead of silently overwriting a newer save. This is conflict detection, not automatic merge.
- **SSH agent scope**: Global `config.use_ssh_agent` applies to direct hosts and tunnel-mode targets. In `ssh_jump_mode=shell` and `transfer_jump_mode=relay`, target authentication happens from the jump-host environment, so target hosts must use `password`, `id_file`, or explicit `use_ssh_agent=true`.
- **Placeholders**: `config.placeholders` is resolved after JSONC parsing only for `host`, `user`, `id_file`, `proxy_command`, and `relay_temp_dir`; do not apply it to secrets or identity fields. `proxy_command` is executed locally by OpenSSH and must be treated as trusted user configuration.
- **i18n**: All UI strings go through `i18n.get(key)`. New strings must be added to both `en` and `zh` dicts in `i18n.py`.
- **Screen management**: TUI uses `curses` and must call `restore_screen()` on exit (handled via `finally` block in `sshgo.py`). `config.tui_screen_policy=isolated` is the default and must not clear scrollback; `private` is opt-in and clears visible screen plus scrollback after curses teardown.
- **JSONC support**: `hosts.json` supports `//` and `#` comments plus trailing commas via `config_store.parse_jsonc()`.

## Verification Commands

Use the smallest set that matches the change. For broad code or documentation sync changes, run:

```bash
python3 -m unittest discover -s tests -p 'test*.py'
python3 -m py_compile sshgo.py host_manager.py host_tree.py config_store.py config_validation.py tui.py audit_logger.py auth.py crypto.py config_parser.py i18n.py terminal_title.py connection_errors.py connection_plan.py connection_planner.py connection_runtime.py sftp_ssh_wrapper.py tests/test_connection_auth_audit.py tests/test_command_plan.py tests/test_terminal_title.py tests/test_tui.py tests/test_audit.py tests/test_config_backup.py tests/test_config_store.py tests/test_config_validation.py tests/test_validation.py tests/test_cli.py tests/test_host_manager.py tests/test_host_tree.py
python3 sshgo.py --validate
git diff --check
```

For TUI smoke checks, run `./sshgo.sh` in a terminal and press `q` to confirm startup and clean exit.
