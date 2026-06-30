# sshgo

[简体中文](README.zh.md)

A modern, secure, and easy-to-manage SSH connection manager with a Text-based User Interface (TUI), full keyboard control, and powerful command-line shortcuts.

Supports password, key-based, and MFA/TOTP authentication, as well as nested jump hosts.

---

## Features

-   **Interactive TUI**: A clear, tree-like interface to browse and manage hosts and groups.
-   **Full Keyboard Navigation**: Navigate, search, and manage hosts without leaving the keyboard.
-   **Comprehensive Host Management**: Add, edit, and delete hosts and groups directly within the TUI.
-   **Powerful CLI Shortcuts**:
    -   Quickly connect to a host: `sshgo <alias>`
    -   Send an initial command after login: `sshgo <alias> <command>`
    -   Upload/download files via SFTP: `sshgo <alias> upload/download ...`
-   **Advanced Authentication**:
    -   Supports password and public key authentication.
    -   Built-in support for MFA/TOTP (Time-based One-Time Password) with prompt-time code generation.
    -   Jump host MFA support with separate code handling.
-   **Nested Jump Hosts**: Intuitively configure jump hosts by nesting `host` nodes in the configuration.
-   **Optional Credential Encryption**: Secure your saved passwords and MFA secrets with a master password. Encryption can be toggled on or off.
-   **~/.ssh/config Import**: Automatically import and group hosts from your existing `~/.ssh/config` file.
-   **Multi-language Support**: Switch between English and Chinese on the fly.
-   **Connection History & Audit**: Recent connections tracked in TUI with stable node identity and JSONL audit logs.
-   **Config Validation**: Validate duplicate names/IDs, invalid ports, unknown fields, and malformed configuration via `--validate`.
-   **Host Detail Preview**: Toggle a detail preview pane in the TUI with `--toggle-details`.

---

## Installation

**1. Dependencies**

This tool has one external dependency:

-   **`expect`**: Required to handle interactive login sessions (e.g., password prompts). You must have it installed on your system.

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

-   `sshgo --audit-full`
    Enable full audit logging for this session. Current full records can include command and jump-chain context; final duration and exit code are not recorded because Python hands off to Expect with `execve`.

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
    "recent_expanded": false,
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
- `audit_full`: Persist full audit records by default, equivalent to always using `--audit-full`.
- `use_ssh_agent`: Use SSH agent authentication globally when `SSH_AUTH_SOCK` exists; hosts can override with their own `use_ssh_agent`.
- `data_dir`: Runtime data directory for history and audit logs.
- `strict_host_key_checking`: `true` uses OpenSSH `accept-new`; `false` restores the older loose mode with `UserKnownHostsFile=/dev/null`.
- `recent_expanded`: Stores whether the TUI Recent group is expanded.
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
  "host": "192.168.1.100:22",
  "user": "dev_user",
  "password": "...",         // Required if not using a key
  "id_file": "~/.ssh/id_rsa",  // Required if not using a password
  "mfa_secret": "...",       // Optional: for TOTP authentication
  "use_ssh_agent": false,    // Optional: overrides config.use_ssh_agent
  "children": [ ... ]        // Optional: makes this host a jump host
}
```

### Jump Host Example

To configure a jump host, simply place the target host(s) inside the `children` array of another host. `sshgo` will automatically use the parent host as a jumper.

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
            "password": "..."
        }
    ]
}
```
