# sshgo

[简体中文](README.zh.md)

A modern, secure, and easy-to-manage SSH connection manager with a Text-based User Interface (TUI), full keyboard control, and powerful command-line shortcuts.

Supports password, key-based, and MFA/TOTP authentication, nested jump hosts, custom OpenSSH `ProxyCommand`, and reusable config placeholders.

---

## Features

-   **Interactive TUI**: A clear, tree-like interface to browse and manage hosts and groups.
-   **Full Keyboard Navigation**: Navigate, search, and manage hosts without leaving the keyboard.
-   **Comprehensive Host Management**: Add, edit, and delete hosts and groups directly within the TUI.
-   **Powerful CLI Shortcuts**:
    -   Quickly connect to a host: `sshgo <alias>`
    -   Send an initial command after login: `sshgo <alias> <command>`
    -   Upload/download files via SFTP: `sshgo <alias> upload/download ...`
    -   Open a standard interactive SFTP prompt: `sshgo --sftp <alias>`
-   **Advanced Authentication**:
    -   Supports password and public key authentication.
    -   Built-in support for MFA/TOTP (Time-based One-Time Password) with prompt-time code generation.
    -   Jump host MFA support with separate code handling.
-   **Nested Jump Hosts**: Intuitively configure jump hosts by nesting `host` nodes in the configuration.
-   **Custom ProxyCommand**: Connect direct hosts through local proxy commands such as `nc -X 5 -x {{local_socks}} %h %p`.
-   **Config Placeholders**: Reuse strings like domains, users, key paths, proxy endpoints, and relay directories with `{{name}}`.
-   **User-owned Credentials**: Passwords and MFA secrets are optional plain config values; protect the config and backups with owner-only permissions, or rely on keys, SSH agent, or manual prompts.
-   **~/.ssh/config Import**: Automatically import and group hosts from your existing `~/.ssh/config` file.
-   **Multi-language Support**: English and Chinese UI via `config.language`.
-   **Connection History & Audit**: Every SSH/SFTP start and exec failure is logged with stable node identity; the TUI Recent group lists the most recent distinct hosts, and `--audit-full` adds launch-context records.
-   **Config Validation**: Validate duplicate names/IDs, invalid ports, unknown fields, and malformed configuration via `--validate`.
-   **Host Detail Preview**: Optional detail preview pane in the TUI.

---

## Installation

**1. Dependencies**

This tool relies on local system SSH tools:

-   **`expect`**: Required to handle interactive login sessions (e.g., password prompts). You must have it installed on your system.
-   **OpenSSH client tools**: `ssh`, `sftp`, and `scp` must be available in `PATH` for connections and file transfer. These are normally preinstalled on macOS and most Linux distributions.

There are **no external Python libraries** to install. All necessary components are bundled.

For `expect`, please use your system's package manager:

-   **macOS (via Homebrew):**
    ```bash
    brew install expect
    ```
-   **Debian/Ubuntu:**
    ```bash
    sudo apt-get update && sudo apt-get install expect
    ```
-   **CentOS/RHEL:**
    ```bash
    sudo yum install expect
    ```

**2. Setup**

Clone the repository to your local machine. For convenience, it is recommended to add an alias to your shell's configuration file (e.g., `~/.bash_profile`, `~/.zshrc`).

```bash
# Replace /path/to/sshgo with the absolute path to this project
alias sshgo='/path/to/sshgo/sshgo.sh'
```

After adding the alias, reload your shell configuration (`source ~/.zshrc`) or restart your terminal.

---

## Usage

### Interactive Mode

Simply run `sshgo` to launch the TUI.

```bash
sshgo
```

**TUI Controls:**

| Key(s)              | Action                                   |
| ------------------- | ---------------------------------------- |
| `↑` / `k`           | Move cursor up                           |
| `↓` / `j`           | Move cursor down                         |
| `Enter`             | Connect to host or expand/collapse group |
| `h` / `l`           | Collapse / Expand the selected group     |
| `a`                 | Add a new host or group                  |
| `e`                 | Edit the selected host or group          |
| `d`                 | Delete the selected host or group        |
| `f`                 | Enter search mode                        |
| `Esc`               | Exit search mode or cancel an action     |
| `q`                 | Quit the application                     |

### Command-Line Shortcuts

-   **Connect to a host:**
    ```bash
    sshgo <host_alias>
    ```
    Exact alias matches are preferred. If a short alias matches multiple hosts, sshgo fails before connecting and prints the candidates instead of guessing.

-   **Send an initial command after login:**
    ```bash
    sshgo <host_alias> ls -la /var/www
    ```
    This starts an interactive SSH session, waits for the remote prompt, sends the command, and then leaves you in the session. It is not a non-interactive command runner and does not return the remote command exit code.

-   **Upload a file:**
    ```bash
    sshgo <host_alias> upload /path/to/local/file.txt /remote/path/
    ```

-   **Download a file:**
    ```bash
    sshgo <host_alias> download /path/to/remote/file.txt /local/path/
    ```

-   **Open an interactive SFTP session:**
    ```bash
    sshgo --sftp <host_alias>
    ```
    This opens the normal OpenSSH `sftp>` prompt using sshgo's host resolution, authentication, MFA, host-key policy, and direct/tunnel jump planning. The positional form `sshgo <host_alias> sftp` is still treated as an SSH remote command.

### File shortcuts inside a remote shell

```bash
sshgo --session-shortcuts <host_alias>
# Initialization is automatic; type commands at the remote prompt without an extra Enter.
sget app.log                  # Download to the local launch directory
sget app.log '~/Downloads/'    # Local ~ must be quoted against remote expansion
sput                          # Enter a local file path, then confirm upload
sput '~/build/app.zip'         # Upload into the current remote directory
```

Each transfer displays both endpoints and asks for local confirmation. Uploads and
existing download destinations require `y`; Enter cancels potential overwrites.
Esc or Ctrl+C cancels the local operation and returns to SSH. SFTP shows its native
progress meter; completion or cancellation returns to the remote prompt without an
extra Enter. Paths with spaces or
Chinese characters work when shell-quoted. Only one regular file per request is
supported; no directories, wildcards, or multi-file requests.

Enable `session_shortcuts_enabled: true` globally under `config`, or on individual
host nodes. Global true enables every supported host; with global false (the default),
only nodes with true are enabled. Node false does not override global true, and parent
node settings are not inherited. CLI and TUI Enter use the same rule; TUI host editing
exposes the node checkbox under Advanced. `--session-shortcuts` and
`--no-session-shortcuts` override both settings for one run.

```json
{
  "config": {"session_shortcuts_enabled": false},
  "hosts": [
    {"type": "host", "name": "server", "host": "server.example.com",
     "user": "alice", "session_shortcuts_enabled": true}
  ]
}
```

Initialization is automatic in ordinary sh/dash, bash (including 3.2) and zsh. Path
encoding uses shell builtins, without od/tr/hexdump. Private temporary text startup
files are removed on normal exit. No remote
binary is installed and no user profile is modified. Functions exist in the current
shell only. Connections use private OpenSSH masters prepared at login; transfers
reuse them without new authentication and fail if they disappear.

Supported combinations are direct/SFTP, tunnel/SFTP, shell/SFTP and shell/relay.
Shell/SFTP uses exec channels through the jump host and needs no TCP forwarding;
standalone transfers keep their existing behavior. Tunnel/relay is unavailable for
this entry. Required exec/subsystem permissions and existing OpenSSH tools still
apply. Menu-only/restricted shells and unusual startup scripts may leave shortcuts
unavailable. The bound target and identity never follow manual `ssh`, `su`, or
`sudo -s` changes.
`--session-shortcuts` cannot be combined with an initial command or `--sftp`.

The functions submit requests, so their shell exit status is not a transfer result.
Read the local completion/failure message. On normal exit private masters and
contexts are cleaned up; abrupt network loss or SIGKILL may leave resources for
manual inspection. ControlPersist's 30-second timeout applies only when idle.

### Global Options

| Option | Purpose |
| --- | --- |
| `--history [--limit N] [--filter name]` | Show recent connection history. |
| `--validate` | Validate the selected configuration without saving. |
| `--doctor` | Check config, dependencies, bundled scripts, runtime data, SSH agent, and host key mode. |
| `--list-backups` | List rotated backups for the selected config file. |
| `--restore-backup <index>` | Restore `hosts.json.bak`, `.bak.1`, or `.bak.2` by index. |
| `--print-command <alias> ...` | Print the resolved SSH/SFTP/transfer handoff command without connecting. |
| `--session-shortcuts` / `--no-session-shortcuts` | Enable/disable session file shortcuts for this run, overriding config; place before the alias. |
| `--sftp <alias>` | Open an interactive `sftp>` prompt for direct or tunnel hosts. |
| `--audit-full` | Enable full audit logging for this process. Records may include command/path context. |
| `-e <path>, --extra-config <path>` | Use a different config file or directory for this process. |
| `-h, --help` | Show the detailed help message. |

---

## Configuration (`hosts.json`)

`hosts.json` is the only supported configuration format. It is JSONC: `//` and `#` comments plus trailing commas are accepted on read, while saves are written as formatted JSON.

`sshgo` loads its configuration file with the following priority:

1.  **`--extra-config <path>` argument**: A temporary path specified on the command line.
2.  **`SSHGO_CONFIG_PATH` environment variable**: A persistent custom path for your config file (e.g., `export SSHGO_CONFIG_PATH="~/.config/sshgo/hosts.json"`).
3.  **User default**: `~/.config/sshgo/hosts.json`, when it exists.
4.  **Project fallback**: The `hosts.json` file located in the project directory.

If `--extra-config` or `SSHGO_CONFIG_PATH` points to a directory, sshgo uses `hosts.json` inside that directory.

sshgo automatically manages an internal `id` field for saved host and group nodes. Preserve it when hand-editing existing nodes.

### Minimal Example

```json
{
  "config": {
    "import_ssh_config": false,
    "language": "en"
  },
  "hosts": [
    {
      "type": "group",
      "name": "Production",
      "expanded": true,
      "children": [
        {
          "type": "host",
          "name": "web-1",
          "host": "web-1.example.com",
          "port": 22,
          "user": "deploy",
          "id_file": "~/.ssh/id_rsa"
        }
      ]
    }
  ]
}
```

### Node Types

The `hosts` list contains two types of nodes: `group` and `host`.

- `group`: `{"type": "group", "name": "My Project", "expanded": true, "children": [...]}`
- `host`: connectable server. `host` and `port` are separate fields; `port` is optional and defaults to `22`.

Common host fields:

| Field | Purpose |
| --- | --- |
| `name` | Alias used in the TUI and CLI. |
| `host` | Hostname or IP address. Do not append `:port`; use `port` instead. |
| `port` | Optional SSH port. Defaults to `22`. |
| `user` | SSH username. |
| `password` | Optional plain password auth value. |
| `id_file` | Private key path. |
| `mfa_secret` | Optional plain TOTP secret. |
| `use_ssh_agent` | Optional per-host override for global SSH agent use. |
| `children` | Nested hosts; a host with children becomes a jump host. |

### Advanced Config

Optional `config` fields include:

| Field | Purpose |
| --- | --- |
| `show_detail_pane`, `show_recent`, `recent_expanded` | TUI display state. |
| `audit_full`, `data_dir` | Runtime audit behavior and runtime data directory. `SSHGO_DATA_DIR` overrides `data_dir` for one process. |
| `strict_host_key_checking` | `true` uses OpenSSH `accept-new`; `false` uses the older loose mode. |
| `tui_screen_policy` | `isolated` uses alternate screen without clearing scrollback; `private` also tries to clear visible screen and scrollback on exit. |
| `terminal_title_enabled`, `terminal_title_target`, `terminal_title_format`, `terminal_title_scope` | Optional tab/window title update before SSH/SFTP/transfer handoff. |
| `default_ssh_jump_mode` | Default nested SSH mode: `shell` or `tunnel`. |
| `default_transfer_jump_mode` | Default nested transfer mode: `tunnel` or `relay`. |
| `relay_temp_dir` | Absolute temporary directory on the jump host for relay transfers. |
| `session_shortcuts_enabled` | Default `false`; enable remote sget/sput entry for CLI/TUI SSH logins. |
| `relay_transfer_timeout` | Expect timeout in seconds for relay file-copy phases; `0` disables this transfer timeout. |
| `placeholders` | String placeholders usable as `{{name}}` in selected connection fields. |
| `theme` | Optional TUI colors: `black`, `red`, `green`, `yellow`, `blue`, `magenta`, `cyan`, `white`, `default`. |

Runtime logs are separate from `hosts.json`. Every SSH/SFTP start and exec failure is appended to `~/.sshgo/history.jsonl`, which also feeds the TUI Recent group; `--audit-full` adds `~/.sshgo/audit-full.jsonl` with launch context such as the remote command and transfer paths. Config saves keep a small backup rotation beside the config file: `hosts.json.bak`, `.bak.1`, and `.bak.2`.

sshgo does not encrypt credentials at rest. Protect `hosts.json` and every rotated backup with owner-only filesystem permissions. Configs from older releases with active encryption or `v2:` credentials are rejected; use a pre-removal release to save plaintext credentials before upgrading.

When terminal titles are enabled, `terminal_title_target: "tab"` works in Ghostty through its window-title compatible sequence. If Ghostty shell integration rewrites the title at the next prompt, set `shell-integration-features = no-title` in Ghostty config. sshgo does not restore the previous title after the remote session exits.

### Proxy, Placeholders, and Jump Hosts

Direct hosts can use an OpenSSH `ProxyCommand`. sshgo resolves only its own `{{name}}` placeholders, then passes the command to OpenSSH. OpenSSH still expands `%h` and `%p`.

```json
{
  "config": {
    "placeholders": {
      "site_domain": "example.com",
      "local_socks": "127.0.0.1:1080",
      "default_user": "admin"
    }
  },
  "hosts": [
    {
      "type": "host",
      "name": "SSH via SOCKS",
      "host": "ssh.{{site_domain}}",
      "user": "{{default_user}}",
      "proxy_command": "nc -X 5 -x {{local_socks}} %h %p"
    }
  ]
}
```

Placeholders are expanded after JSONC parsing and only in `host`, `user`, `id_file`, `proxy_command`, and `config.relay_temp_dir`. They are not expanded in secrets such as `password` or `mfa_secret`.

`proxy_command` applies to the host where it is configured. When that host is used as a jump host, child connections use the parent `proxy_command` for the first hop. A `proxy_command` on the nested target itself is rejected because nested `tunnel` mode already generates its own `ProxyCommand=ssh -W ...`, while `shell` and `relay` modes run target operations from the jump host environment.

`ProxyCommand` is executed locally by OpenSSH. Configure only trusted commands, and do not build `proxy_command` values from untrusted input.

To configure a jump host, place target hosts inside a host's `children` array. Nested SSH defaults to `ssh_jump_mode: "shell"`, which logs in to the parent first and starts target SSH from that shell. Set `ssh_jump_mode: "tunnel"` to use OpenSSH forwarding instead.

File transfer defaults to `transfer_jump_mode: "tunnel"`, which is true local SFTP and requires TCP forwarding on the jump host. Use `transfer_jump_mode: "relay"` only when forwarding is disabled and temporary jump-host storage is acceptable. Relay supports upload/download shortcuts, prints transfer phases, uses `relay_transfer_timeout` for file-copy phases, and does not provide a live target `sftp>` prompt.

```json
{
    "type": "host",
    "name": "My Jump Host",
    "host": "jump.example.com",
    "user": "jump_user",
    "id_file": "~/.ssh/jump_key",
    "children": [
        {
            "type": "host",
            "name": "Internal API Server",
            "host": "api.internal.example.com",
            "user": "api_user",
            "password": "...",
            "ssh_jump_mode": "shell",
            "transfer_jump_mode": "relay"
        }
    ]
}
```
