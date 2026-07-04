# Custom ProxyCommand and placeholders

## Metadata

- slug: custom-proxy-command
- status: approved
- owner: PM/Architect/Engineer
- related_adr: none
- related_roadmap: docs/roadmap.md#2026-07
- related_specs:
  - docs/specs/config-format-jsonc.md
  - docs/specs/connection-auth-audit-hardening.md
  - docs/specs/jump-host-connection-modes.md
  - docs/specs/security-hardening.md

## Problem Background

Some SSH targets are not reachable through a normal direct TCP connection or through sshgo's nested jump-host model. A common example is a target that must be reached through a local SOCKS proxy:

```bash
ssh -o 'ProxyCommand=nc -X 5 -x 127.0.0.1:1080 %h %p' admin@ssh.example.com
```

sshgo currently supports an internally generated `ProxyCommand=ssh -W %h:%p ...` for nested jump-host `tunnel` mode, but it does not let a user configure an arbitrary OpenSSH `ProxyCommand` for a direct host. Users also need a way to define repeated local endpoints such as `127.0.0.1:1080` once and reuse them across host fields.

## Goals

- Add a host-level `proxy_command` field for custom OpenSSH `ProxyCommand` values.
- Add global `config.placeholders` for lightweight string reuse.
- Resolve placeholders after JSONC parsing and before command construction.
- Preserve OpenSSH semantics: sshgo expands only `{{name}}`; OpenSSH still expands `%h` and `%p`.
- Support direct SSH connections, direct remote-command shortcuts, and direct SFTP upload/download paths.
- Apply a parent jump host's `proxy_command` to the first hop when a child target is selected.
- Support placeholders in a small allowlist of connection fields.
- Preserve existing nested jump-host behavior for `shell`, `tunnel`, and `relay`.
- Keep Python stdlib-only and preserve the current Python-to-Expect `execve` handoff model.
- Validate obvious configuration errors instead of silently ignoring them.

## Non-goals

- Do not implement `ProxyJump` as a separate user-facing field.
- Do not stack multiple `ProxyCommand` values for a single OpenSSH connection.
- Do not import `ProxyCommand` from `~/.ssh/config` in this change.
- Do not implement a full OpenSSH config parser.
- Do not perform JSONC text replacement before `json.loads`.
- Do not turn every JSON string field into a template.
- Do not expand shell environment variables such as `$SOCKS_PROXY` or `${SOCKS_PROXY}`.
- Do not support placeholders in `password`, `mfa_secret`, `name`, `id`, `type`, `children`, or `expanded`.
- Do not apply a nested target's own `proxy_command` inside nested jump-host modes.
- Do not compose multiple generations of parent jump-host `proxy_command` for deeper-than-one-level nesting in this version.

## Configuration

Add an optional `proxy_command` field to `host` nodes:

```json
{
  "type": "host",
  "name": "SSH via SOCKS",
  "host": "ssh.example.com:22",
  "user": "admin",
  "proxy_command": "nc -X 5 -x 127.0.0.1:1080 %h %p"
}
```

To avoid repeating local proxy endpoints, add optional placeholders under `config`:

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
      "host": "ssh.{{site_domain}}:22",
      "user": "{{default_user}}",
      "proxy_command": "nc -X 5 -x {{local_socks}} %h %p"
    }
  ]
}
```

Runtime values become:

```text
host = ssh.example.com:22
user = admin
proxy_command = nc -X 5 -x 127.0.0.1:1080 %h %p
```

The original JSONC remains unchanged when saved; sshgo does not write expanded runtime values back to `hosts.json`.

## Placeholder Rules

- Placeholder syntax is exactly `{{name}}`.
- Placeholder names must match `[A-Za-z_][A-Za-z0-9_]*`.
- Placeholder values must be non-empty strings.
- Replacement is one-pass and non-recursive.
- Undefined placeholders fail validation.
- Placeholder expansion happens after JSONC parsing, not as raw text replacement.
- Shell variables such as `$VAR` and `${VAR}` are not expanded by sshgo.
- OpenSSH tokens such as `%h` and `%p` are not expanded by sshgo.

First-version placeholder expansion only applies to:

```text
host
user
id_file
proxy_command
config.relay_temp_dir
```

It does not apply to:

```text
name
password
mfa_secret
id
type
children
expanded
```

This keeps identity, audit, search, and encrypted secret behavior stable.

## Behavior

For a direct host with:

```json
{
  "host": "ssh.{{site_domain}}:22",
  "user": "{{default_user}}",
  "proxy_command": "nc -X 5 -x {{local_socks}} %h %p"
}
```

sshgo should create an OpenSSH invocation equivalent to:

```bash
ssh -o 'ProxyCommand=nc -X 5 -x 127.0.0.1:1080 %h %p' admin@ssh.example.com
```

OpenSSH remains responsible for expanding `%h` to `ssh.example.com` and `%p` to `22` inside the proxy command.

Direct SFTP upload/download should use the same resolved proxy command through the local OpenSSH SFTP client:

```bash
sftp -b <batchfile> -S ./sftp_ssh_wrapper.py -o 'ProxyCommand=nc -X 5 -x 127.0.0.1:1080 %h %p' admin@ssh.example.com
```

## Interaction With Jump Modes

Existing nested jump-host modes already consume the same OpenSSH concept in some paths. This change keeps those semantics explicit.

| Scenario | Behavior |
|---|---|
| Direct host + `proxy_command` | Use the custom `ProxyCommand` |
| Direct SFTP + `proxy_command` | Use the custom `ProxyCommand` |
| Nested target + target `proxy_command` | Invalid configuration |
| Nested transfer + target `proxy_command` | Invalid configuration |
| Parent jump host has `proxy_command` and child target is selected | Use the parent `proxy_command` for the first hop to the jump host |

In this version, "parent jump host has `proxy_command`" means a host that is not itself nested under another host. A nested intermediate host is still a nested target for its own parent, even if it also has `children`; it must not define its own `proxy_command`.

For nested `shell`, the parent `proxy_command` is passed to the first local SSH command that logs in to the jump host. For nested `tunnel` and local SFTP tunnel, `HostManager` generates the final `ProxyCommand=ssh -W ...` command used to reach the parent jump host and passes it to Expect as `-tunnel-proxy-command`. Because OpenSSH expands `%h` and `%p` in the outer `ProxyCommand`, sshgo escapes percent signs in the embedded parent proxy command as `%%` so the inner SSH process can expand them against the parent jump host instead of the child target.

For relay transfers, the parent `proxy_command` is used by local SSH/SCP commands that connect to the jump host.

## Validation Rules

`validate_hosts_config()` should enforce:

1. `proxy_command` is an allowed host node field.
2. `proxy_command` on a host must be a non-empty string.
3. `proxy_command` on a group node is invalid.
4. `config.placeholders` must be an object when present.
5. Placeholder names must match `[A-Za-z_][A-Za-z0-9_]*`.
6. Placeholder values must be non-empty strings.
7. Every placeholder used in allowed fields must resolve.
8. Malformed placeholder braces such as `{{name`, `name}}`, or `{{bad-name}}` are invalid.
9. Resolved `host` values must pass existing hostname/port validation.
10. Resolved `config.relay_temp_dir` must be an absolute path.
11. A nested target with `proxy_command` is invalid.

Suggested user-facing validation messages:

- `Invalid proxy_command: must be a non-empty string`
- `Invalid placeholders: must be an object`
- `Invalid placeholder name: {name}`
- `Invalid placeholder value for {name}: must be a non-empty string`
- `Unknown placeholder: {name}`
- `proxy_command cannot be used with nested jump host modes`

Messages must be added to both English and Chinese i18n dictionaries.

## Technical Design

### HostManager

Add `proxy_command` to the host save whitelist and add `placeholders` to the default config. Runtime config must be created through `_default_config()` / `_merge_config()` so the mutable `placeholders` map is copied per `HostManager` instance instead of shared globally.

Add compiled regexes for valid placeholder replacement and malformed brace detection:

```python
PLACEHOLDER_RE = re.compile(r"{{([A-Za-z_][A-Za-z0-9_]*)}}")
PLACEHOLDER_TOKEN_RE = re.compile(r"{{([^{}]*)}}")
PLACEHOLDER_BRACE_RE = re.compile(r"{{|}}")
PLACEHOLDER_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
```

Add runtime helpers:

```python
def _resolve_placeholders(self, value):
    if not isinstance(value, str):
        return value

    placeholders = self.config.get("placeholders", {})
    if not isinstance(placeholders, dict):
        placeholders = {}

    # Reject malformed placeholder-looking text before replacement.
    for match in PLACEHOLDER_TOKEN_RE.finditer(value):
        name = match.group(1)
        if not PLACEHOLDER_NAME_RE.match(name):
            raise PlaceholderResolutionError(...)

    for match in PLACEHOLDER_BRACE_RE.finditer(value):
        if match is outside a valid token span:
            raise PlaceholderResolutionError(...)

    def replace(match):
        name = match.group(1)
        if name not in placeholders:
            raise PlaceholderResolutionError(...)
        return str(placeholders[name])

    return PLACEHOLDER_RE.sub(replace, value)
```

Connection paths should read resolved values through helpers instead of accessing raw node strings directly:

- `_parse_host_port(node)` resolves `node["host"]`.
- user values passed to OpenSSH/Expect are resolved.
- `id_file` values passed to OpenSSH/Expect are resolved.
- `proxy_command` is resolved before being passed as `-proxy-command`.
- A parent jump host's `proxy_command` is resolved before being passed as `-j-proxy-command` for shell jump and relay first-hop commands.
- Nested SSH tunnel and SFTP tunnel paths receive a Python-generated `-tunnel-proxy-command` instead of rebuilding `ssh -W` inside Expect.
- `_relay_temp_path()` resolves `config.relay_temp_dir`.

TUI edit forms must use the raw configured host value through `raw_host_port()` instead of `_parse_host_port()`. This preserves `{{name}}` placeholders when a user edits and saves a host without touching that field.

`add_node()` and `update_node()` must not persist `proxy_command` on a host nested directly under another host. `add_node()` should drop it when the parent is a host, and `update_node()` should remove any existing nested-target value before applying submitted data. This keeps the save path aligned with validation even if callers bypass the TUI.

For supported direct hosts and parent jump hosts, `update_node()` should remove `proxy_command` when the TUI submits `None`, an empty string, or whitespace-only text. Non-empty values should be saved as strings, preserving the user's command text except for outer whitespace trimming.

Runtime command construction should still handle unresolved placeholders defensively with a clear user-facing error, even though `--validate` catches valid persisted configs.

Runtime command construction should also fail fast when a selected nested target, or a nested intermediate parent used by that target, contains `proxy_command`. This prevents invalid persisted configs from being silently ignored when users connect without running `--validate`.

### login.exp

Add a `-proxy-command` argument:

```tcl
set custom_proxy_command ""

"-proxy-command" { set custom_proxy_command $value }
```

Add a separate `-j-proxy-command` argument for the parent jump host:

```tcl
set jumper_proxy_command ""

"-j-proxy-command" { set jumper_proxy_command $value }
```

When building a direct target SSH command, append:

```tcl
if {$custom_proxy_command != ""} {
    lappend cmd -o "ProxyCommand=$custom_proxy_command"
}
```

Do not add a second `ProxyCommand` when `jump_mode=tunnel` is generating its own jump-host tunnel command.

When `jump_mode=shell`, add `jumper_proxy_command` to the first-hop SSH command. When `jump_mode=tunnel`, consume the Python-generated `-tunnel-proxy-command` and add it as the SSH `ProxyCommand` value. `login.exp` should not rebuild the inner `ssh -W` command.

Add a hidden `-print-command` test hook that renders the final SSH command and exits without spawning a connection.

### sftp_login.exp

Add the same `-proxy-command` argument and append:

```tcl
if {$custom_proxy_command != ""} {
    lappend cmd -o "ProxyCommand=$custom_proxy_command"
}
```

The Python layer should avoid calling SFTP with both a nested jump `-J` and a nested target's own custom `proxy_command`.

For nested SFTP, consume the Python-generated `-tunnel-proxy-command` and add it as the SFTP `ProxyCommand` value. `sftp_login.exp` should not rebuild the inner `ssh -W` command and should not accept a separate jump-host identity argument; the jump host identity file belongs inside the generated tunnel command.

Current direct/tunnel SFTP runs OpenSSH `sftp` in batch mode. Keep the custom or tunnel `ProxyCommand` behavior above while preserving `-b <batchfile>` and `-S sftp_ssh_wrapper.py`, which removes OpenSSH `sftp -b`'s implicit `BatchMode=yes` before execing `ssh`.

Add a hidden `-print-command` test hook that renders the final SFTP command and exits without spawning a connection.

### relay_transfer.exp

Accept `-j-proxy-command` and apply it to local SSH/SCP commands that connect to the jump host. Relay target-side SCP commands run from the jump host shell and do not use the local parent proxy command.

### TUI

Add an optional host form field:

- label: `ProxyCommand`
- name: `proxy_command`
- type: text

The field is shown only for direct hosts and host nodes that may act as parent jump hosts. It is hidden when editing or adding a nested target under a host parent. Detail panes should display the configured proxy command only for non-nested hosts. Empty values should not be shown.

### SSH config import

Do not import `ProxyCommand` from `~/.ssh/config` in this change. The current importer is intentionally small and only maps basic host fields. OpenSSH config supports quoting, `Match`, `Include`, and other behaviors that require a larger parser design.

## Security Considerations

`ProxyCommand` is a local command executed by OpenSSH. sshgo should treat `hosts.json` as trusted local user configuration and preserve standard OpenSSH behavior.

Implementation constraints:

- Do not place `proxy_command` in environment variables.
- Do not pass secrets through `proxy_command`.
- Do not parse or rewrite the inner command string beyond documented `{{name}}` placeholder replacement.
- Do not expand `%h` or `%p`; OpenSSH owns that expansion.
- Do not expand `$VAR` or `${VAR}`; shell environment expansion is intentionally not part of sshgo config semantics.
- Do not add Python package dependencies for command parsing.
- Do not add `proxy_command` to audit `command` fields unless a later audit schema explicitly defines that behavior.

User-facing docs should clearly state that users should not put untrusted input in `proxy_command`.

## Acceptance Criteria

1. A direct host with `proxy_command` can start an interactive SSH connection through OpenSSH `ProxyCommand`.
2. A direct host with `proxy_command` can run a remote command shortcut through OpenSSH `ProxyCommand`.
3. A direct host with `proxy_command` can use upload/download through local SFTP `ProxyCommand`.
4. The example `nc -X 5 -x {{local_socks}} %h %p` resolves only `{{local_socks}}` before OpenSSH receives it.
5. `{{site_domain}}`, `{{default_user}}`, and `{{local_socks}}` can resolve from `config.placeholders` in allowed fields.
6. A child target selected under a parent jump host with `proxy_command` uses the parent command for the first hop.
7. Nested tunnel generation escapes embedded parent proxy `%h/%p` as `%%h/%%p` before passing the outer `ProxyCommand` to OpenSSH.
8. `--validate` accepts valid placeholder usage in allowed fields.
9. `--validate` rejects empty, non-string, group-level, unresolved-placeholder, invalid-placeholder, and nested-conflict `proxy_command` configurations.
10. TUI add/edit can create, modify, and clear the `proxy_command` field for direct hosts and parent jump hosts, and does not expose it for nested targets.
11. Runtime SSH, SFTP, and relay command construction rejects persisted nested-target `proxy_command` instead of silently ignoring it.
12. Existing jump-host `shell`, `tunnel`, `relay`, auth, audit, and config-save behavior remains unchanged.
13. Existing tests continue to pass.

## Verification Plan

Run the standard narrow project checks:

```bash
python3 -m unittest discover -s tests -p 'test*.py'
python3 -m py_compile sshgo.py host_manager.py tui.py audit_logger.py auth.py crypto.py config_parser.py i18n.py tests/test_connection_auth_audit.py
python3 sshgo.py --validate
git diff --check
```

Add focused tests for:

- Valid direct host `proxy_command` validation.
- Empty and non-string `proxy_command` validation failures.
- Group-level `proxy_command` validation failure.
- Config-level `placeholders` validation.
- Placeholder resolution in SSH command arguments.
- Placeholder resolution in SFTP command arguments.
- Placeholder resolution in relay temp paths.
- Missing placeholder validation failure.
- Nested target conflict validation.
- `execute_interactive_connection()` passing `-proxy-command` to `login.exp`.
- `execute_file_transfer()` passing `-proxy-command` to `sftp_login.exp`.
- Parent jump-host `proxy_command` passing as `-j-proxy-command` for shell jump and relay first-hop commands.
- Python-generated `-tunnel-proxy-command` passing for nested SSH tunnel and SFTP tunnel.
- Nested SFTP omits the obsolete standalone jump-host identity argument.
- Nested tunnel preview escaping parent proxy `%h/%p` as `%%h/%%p`.
- `login.exp` and `sftp_login.exp` `-print-command` rendering the final command without spawning.
- `login.exp` command construction for custom `ProxyCommand`.
- `sftp_login.exp` command construction for custom `ProxyCommand`.
- TUI update clearing `proxy_command`.
- TUI edit hides `proxy_command` for nested targets.
- `add_node()` and `update_node()` drop nested-target `proxy_command`.
- Runtime command builders reject nested-target `proxy_command`.

Manual smoke test, when an appropriate local proxy is available:

```bash
./sshgo.sh <alias>
./sshgo.sh <alias> 'printf SSHGO_PROXY_OK'
./sshgo.sh <alias> upload <local-file> <remote-file>
./sshgo.sh <alias> download <remote-file> <local-file>
```

## Review Status

- Product scope: approved
- Technical design: approved
- Implementation: complete
- Verification: passed
