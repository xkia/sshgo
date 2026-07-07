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
-   **Optional Credential Encryption**: Secure your saved passwords and MFA secrets with a master password. Encryption can be toggled on or off.
-   **~/.ssh/config Import**: Automatically import and group hosts from your existing `~/.ssh/config` file.
-   **Multi-language Support**: Switch between English and Chinese on the fly.
-   **Connection History & Audit**: Recent connections tracked in TUI with stable node identity and JSONL audit logs.
-   **Config Validation**: Validate duplicate names/IDs, invalid ports, unknown fields, and malformed configuration via `--validate`.
-   **Host Detail Preview**: Toggle a detail preview pane in the TUI with `--toggle-details`.

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

### Global Options

-   `sshgo --toggle-encryption`
    Enable or disable master password encryption for `hosts.json`.

-   `sshgo --toggle-ssh-config`
    Enable or disable importing hosts from `~/.ssh/config`.

-   `sshgo --toggle-details`
    Toggle the host detail preview pane in the TUI.

-   `sshgo --toggle-ssh-agent`
    Enable or disable SSH agent for this session.

-   `sshgo --toggle-language`
    Toggle the display language between English and Chinese.

-   `sshgo --history`
    Show recent connection history. Use `--limit N` (default: 10) and `--filter <name>` to narrow results.

-   `sshgo --validate`
    Validate the configuration file for errors.

-   `sshgo --doctor`
    Run local diagnostics for config validity, `expect`, OpenSSH client tools, bundled Expect scripts and transfer helpers, runtime data directory writability, SSH agent state, and host key mode.

-   `sshgo --list-backups`
    List rotated backups for the resolved `hosts.json` path.

-   `sshgo --restore-backup <index>`
    Restore a rotated backup by index. `0` means `hosts.json.bak`, `1` means `hosts.json.bak.1`, and so on.

-   `sshgo --print-command <host_alias> [command|upload|download ...]`
    Print the resolved sshgo handoff command without connecting. Passwords and MFA secrets are not printed.

-   `sshgo --print-command --sftp <host_alias>`
    Print the resolved interactive SFTP handoff command without connecting.

-   `sshgo --sftp <host_alias>`
    Open an interactive SFTP session. Nested hosts require effective `transfer_jump_mode: "tunnel"`; `relay` is rejected because it is not a live SFTP session.

-   `sshgo --audit-full`
    Enable full audit logging for this session. Current full records can include command, path, and jump-chain context that may contain sensitive arguments; final duration and exit code are not recorded because Python hands off to Expect with `execve`.

-   `sshgo --edit`
    Open the TUI directly in edit mode.

-   `sshgo -e <path>, --extra-config <path>`
    Use a different configuration file or configuration directory for this session only. Overrides `SSHGO_CONFIG_PATH`.

-   `sshgo -h, --help`
    Show the detailed help message.

---

## Configuration (`hosts.json`)

`hosts.json` is the only supported configuration format. TOML and YAML are not supported because sshgo avoids external Python package dependencies and requires every supported format to work for the full read/write lifecycle.

`sshgo` loads its configuration file with the following priority:

1.  **`--extra-config <path>` argument**: A temporary path specified on the command line.
2.  **`SSHGO_CONFIG_PATH` environment variable**: A persistent custom path for your config file (e.g., `export SSHGO_CONFIG_PATH="~/.config/sshgo/hosts.json"`).
3.  **User default**: `~/.config/sshgo/hosts.json`, when it exists.
4.  **Project fallback**: The `hosts.json` file located in the project directory.

If `--extra-config` or `SSHGO_CONFIG_PATH` points to a directory, sshgo uses `hosts.json` inside that directory.

All host information is stored in the selected `hosts.json` file. For convenience, this file supports single-line comments using `//` and `#` symbols, as well as trailing commas.

sshgo automatically manages an internal `id` field for saved host and group nodes. This keeps Recent entries linked to the current node after a rename. You do not need to write IDs manually; existing configs are migrated during normal startup or edit flows and saved back through the normal atomic write path. `--validate` remains read-only.

Before replacing an existing config file, sshgo keeps a small best-effort backup rotation beside it:

- `hosts.json.bak`
- `hosts.json.bak.1`
- `hosts.json.bak.2`

Use `sshgo --list-backups` to inspect the rotation and `sshgo --restore-backup <index>` to restore one. Restore validates the selected backup first and keeps the pre-restore active config as the newest backup when it exists.

New audit/history records include `node_id`, `host`, `port`, and `endpoint` so Recent can distinguish nodes that share the same host and user but use different ports.

Runtime history and audit data are separate from `hosts.json`. By default, sshgo writes:

- `~/.sshgo/history.jsonl`
- `~/.sshgo/audit-simple.jsonl`
- `~/.sshgo/audit-full.jsonl` when full audit is enabled

Set `SSHGO_DATA_DIR` or `config.data_dir` to use a different runtime data directory. `SSHGO_DATA_DIR` takes precedence for the current process.

### Top-Level Structure

```json
{
  "config": {
    "encryption_enabled": true,
    "encryption_salt": "...",
    "import_ssh_config": true,
    "language": "en",
    "show_detail_pane": true,
    "audit_full": false,
    "use_ssh_agent": false,
    "data_dir": null,
    "strict_host_key_checking": true,
    "show_recent": true,
    "recent_expanded": false,
    "tui_screen_policy": "isolated",
    "terminal_title_enabled": false,
    "terminal_title_target": "tab",
    "terminal_title_format": "alias_host",
    "terminal_title_scope": "auto",
    "default_ssh_jump_mode": "shell",
    "default_transfer_jump_mode": "tunnel",
    "relay_temp_dir": "/tmp",
    "placeholders": {
      "site_domain": "example.com",
      "local_socks": "127.0.0.1:1080"
    },
    "theme": {
      "highlight_fg": "white",
      "highlight_bg": "blue",
      "prefix_color": "red"
    }
  },
  "hosts": [
    // ... List of host and group nodes ...
  ]
}
```

Important `config` fields:

- `import_ssh_config`: Import read-only hosts from `~/.ssh/config`.
- `show_detail_pane`: Show or hide the TUI host detail preview pane.
- `audit_full`: Persist full audit records by default, equivalent to always using `--audit-full`. Full records can include command/path context that may contain sensitive arguments.
- `use_ssh_agent`: Use SSH agent authentication globally when `SSH_AUTH_SOCK` exists; hosts can override with their own `use_ssh_agent`. Nested targets using `ssh_jump_mode: "shell"` or `transfer_jump_mode: "relay"` cannot rely on the global setting because target authentication runs from the jump-host environment; configure target `password`, `id_file`, or `use_ssh_agent: true` explicitly for those modes.
- `data_dir`: Runtime data directory for history and audit logs.
- `strict_host_key_checking`: `true` uses OpenSSH `accept-new`; `false` restores the older loose mode with `UserKnownHostsFile=/dev/null`.
- `show_recent`: Show or hide the TUI Recent group.
- `recent_expanded`: Stores whether the TUI Recent group is expanded.
- `tui_screen_policy`: `isolated` uses the terminal alternate screen and does not clear scrollback; `private` also attempts to clear the visible screen and scrollback after TUI exit.
- `terminal_title_enabled`: When `true`, set the terminal tab/window title before SSH, SFTP, upload/download, or relay handoff. Defaults to `false`.
- `terminal_title_target`: Title target, one of `tab`, `window`, or `both`. For Ghostty, `tab` uses Ghostty's window-title compatible sequence so the visible tab/surface title updates.
- `terminal_title_format`: Title body format, one of `alias`, `host`, or `alias_host`.
- `terminal_title_scope`: `auto` only emits title sequences for known compatible terminal contexts; `always` emits when enabled. sshgo does not restore the previous title after the remote session exits.
  If Ghostty shell integration rewrites the title at the next prompt, set `shell-integration-features = no-title` in Ghostty config.
- `default_ssh_jump_mode`: Default nested SSH mode, either `shell` or `tunnel`.
- `default_transfer_jump_mode`: Default nested transfer mode, either `tunnel` or `relay`.
- `relay_temp_dir`: Absolute temporary directory on the jump host for `transfer_jump_mode: "relay"`.
- `placeholders`: Optional string placeholders usable as `{{name}}` in connection fields.
- `theme`: Optional TUI colors. Supported color names are `black`, `red`, `green`, `yellow`, `blue`, `magenta`, `cyan`, `white`, and `default`.

### Node Types

The `hosts` list contains two types of nodes: `group` and `host`.

**1. `group`**

Used to organize hosts. Groups can be nested.

```json
{
  "type": "group",
  "name": "My Project",
  "expanded": true, // Whether the group is expanded by default in the TUI
  "children": [ ... ] // A list of other group or host nodes
}
```

**2. `host`**

Represents a connectable server. A `host` can also act as a **jump host** if it contains a `children` list.

```json
{
  "type": "host",
  "name": "My Web Server",
  "host": "192.168.1.100",
  "port": 22,              // Optional; defaults to 22
  "user": "dev_user",
  "password": "...",         // Required if not using a key
  "id_file": "~/.ssh/id_rsa",  // Required if not using a password
  "mfa_secret": "...",       // Optional: for TOTP authentication
  "use_ssh_agent": false,    // Optional: overrides config.use_ssh_agent
  "proxy_command": "nc -X 5 -x {{local_socks}} %h %p", // Optional
  "ssh_jump_mode": "shell",  // Optional: shell or tunnel
  "transfer_jump_mode": "tunnel", // Optional: tunnel or relay
  "children": [ ... ]        // Optional: makes this host a jump host
}
```

### Custom ProxyCommand and Placeholders

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

This resolves to a connection equivalent to:

```bash
ssh -o 'ProxyCommand=nc -X 5 -x 127.0.0.1:1080 %h %p' admin@ssh.example.com
```

Placeholders are expanded after JSONC parsing and only in `host`, `user`, `id_file`, `proxy_command`, and `config.relay_temp_dir`. They are not expanded in secrets such as `password` or `mfa_secret`.

`proxy_command` applies to the host where it is configured. When that host is used as a jump host, child connections use the parent `proxy_command` for the first hop. A `proxy_command` on the nested target itself is rejected because nested `tunnel` mode already generates its own `ProxyCommand=ssh -W ...`, while `shell` and `relay` modes run target operations from the jump host environment. In multi-level trees, only a non-nested parent jump host can define `proxy_command`; a nested intermediate host must not define its own value. The TUI only shows the `ProxyCommand` field for direct hosts and parent jump hosts. `ProxyCommand` entries from `~/.ssh/config` are not imported; define them explicitly in `hosts.json` when sshgo should manage them.

`ProxyCommand` is executed locally by OpenSSH. Configure only trusted commands, and do not build `proxy_command` values from untrusted input.

### Jump Host Example

To configure a jump host, place the target host(s) inside the `children` array of another host. Nested SSH defaults to `ssh_jump_mode: "shell"`: `sshgo` logs in to the parent host first, then starts SSH to the target from that parent shell. Set `ssh_jump_mode: "tunnel"` to use OpenSSH forwarding instead.

File transfer defaults to `transfer_jump_mode: "tunnel"`, which is true local SFTP and requires the jump host to allow TCP forwarding. Interactive SFTP (`sshgo --sftp <alias>`) also requires direct or tunnel mode. Set `transfer_jump_mode: "relay"` only when forwarding is disabled and you accept that files are temporarily copied through the jump host with `scp`; relay supports upload/download shortcuts, but not a live `sftp>` prompt. If local-to-jump `scp` fails with a protocol incompatibility, relay retries that hop with legacy scp protocol.

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
            "host": "10.0.1.50",
            "user": "api_user",
            "password": "...",
            "ssh_jump_mode": "shell",
            "transfer_jump_mode": "relay"
        }
    ]
}
```
