# Custom ProxyCommand and placeholders

## Metadata

- slug: custom-proxy-command
- status: approved
- owner: PM/Architect/Engineer
- related_roadmap: docs/roadmap.md#2026-07
- related_specs:
  - docs/specs/config-format-jsonc.md
  - docs/specs/host-port-schema-split.md
  - docs/specs/jump-host-connection-modes.md
  - docs/specs/security-hardening.md

## Problem

Some hosts must be reached through an OpenSSH `ProxyCommand`, for example a
local SOCKS proxy:

```bash
ssh -o 'ProxyCommand=nc -X 5 -x 127.0.0.1:1080 %h %p' admin@ssh.example.com
```

sshgo supports generated tunnel proxy commands for nested jump hosts, but users
also need a trusted, host-level custom `proxy_command` for direct hosts and for
the first hop to a parent jump host.

## Goals

- Support optional host-level `proxy_command`.
- Support `config.placeholders` for small repeated strings.
- Expand only `{{name}}` placeholders; leave OpenSSH `%h` and `%p` untouched.
- Apply placeholders only to allowed connection fields.
- Preserve stdlib-only Python and the Python-to-Expect `execve` handoff model.
- Reject invalid or ambiguous proxy-command usage during validation and runtime
  command planning.

## Non-Goals

- No user-facing `ProxyJump` field.
- No stacking multiple custom `ProxyCommand` values for one OpenSSH connection.
- No `ProxyCommand` import from `~/.ssh/config`.
- No raw JSONC text replacement before parsing.
- No placeholder support in secrets or identity fields.
- No shell environment expansion such as `$SOCKS_PROXY`.
- No nested target-owned `proxy_command` inside jump-host modes.
- No full OpenSSH config parser.

## Configuration

Host-level field:

```json
{
  "type": "host",
  "name": "SSH via SOCKS",
  "host": "ssh.example.com",
  "user": "admin",
  "proxy_command": "nc -X 5 -x 127.0.0.1:1080 %h %p"
}
```

Optional placeholders:

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

sshgo resolves placeholders at runtime and during validation. It does not save
expanded values back to `hosts.json`.

## Placeholder Rules

- Syntax is exactly `{{name}}`.
- Names must match `[A-Za-z_][A-Za-z0-9_]*`.
- Values must be non-empty strings.
- Replacement is one-pass and non-recursive.
- Undefined placeholders fail validation.
- Malformed braces fail validation.
- `%h` and `%p` remain OpenSSH tokens.

Allowed fields:

```text
host
user
id_file
proxy_command
config.relay_temp_dir
```

Disallowed fields include:

```text
name
password
mfa_secret
id
type
children
expanded
```

## Behavior

Direct SSH and remote-command shortcuts pass the resolved proxy command to
OpenSSH:

```bash
ssh -o 'ProxyCommand=nc -X 5 -x 127.0.0.1:1080 %h %p' admin@ssh.example.com
```

Direct SFTP upload/download and interactive SFTP use the same resolved
`ProxyCommand` through the local OpenSSH SFTP client. Batch upload/download
still preserves `-b <batchfile>` and `-S sftp_ssh_wrapper.py`.

Nested behavior:

| Scenario | Result |
| --- | --- |
| Direct host + `proxy_command` | Use the custom proxy command |
| Direct SFTP + `proxy_command` | Use the custom proxy command |
| Nested target + target `proxy_command` | Invalid |
| Parent jump host has `proxy_command` | Use it for the first local hop to the parent |

For generated tunnel proxy commands, sshgo escapes embedded parent proxy `%h`
and `%p` as `%%h` and `%%p` so the inner OpenSSH process receives the intended
tokens for the parent jump host.

## Validation Rules

`validate_hosts_config()` rejects:

- non-string or empty `proxy_command`;
- `proxy_command` on group nodes;
- `proxy_command` on nested target hosts;
- invalid `config.placeholders`;
- malformed, unknown, or disallowed placeholders in allowlisted fields;
- placeholder-resolved host/port or relay temp dir values that fail their normal
  validation.

Runtime command planning also fails fast for unresolved placeholders or nested
proxy-command conflicts, even if the user did not run `--validate`.

## Security Constraints

`ProxyCommand` is executed locally by OpenSSH and is trusted local user
configuration. sshgo must not:

- place `proxy_command` in secret environment variables;
- pass secrets through `proxy_command`;
- parse or rewrite the inner command beyond documented `{{name}}` replacement;
- expand `%h`, `%p`, `$VAR`, or `${VAR}`;
- add `proxy_command` to audit command fields without a later audit schema.

## Acceptance Criteria

1. Direct SSH, remote command, upload/download, and interactive SFTP can use a
   host-level `proxy_command`.
2. Parent jump-host `proxy_command` applies to the first local hop for shell,
   tunnel, SFTP tunnel, and relay paths.
3. Nested targets cannot define their own `proxy_command`.
4. Placeholder expansion works only in the documented allowlist.
5. OpenSSH owns `%h` and `%p` expansion.
6. TUI add/edit can create, update, hide, and clear `proxy_command` according to
   the nested/direct host context.
7. Existing jump-host, auth, audit, and config-save behavior remains unchanged.

## Verification

Use the broad verification commands in `AGENTS.md`. Focused tests should cover
validation, placeholder resolution, direct SSH/SFTP args, parent jump-host
proxy behavior, nested conflict rejection, TUI form visibility, and Expect
`-print-command` rendering.

## Review Status

- status: approved
- verdict: PASS
- notes: Detailed implementation pseudocode and completed validation logs were
  compressed after implementation. Current behavior lives in source modules and
  focused tests.
