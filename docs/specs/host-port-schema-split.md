# Host Port Schema Split

## Metadata

- slug: host-port-schema-split
- status: approved
- owner: PM/Architect/Engineer
- related_roadmap: docs/roadmap.md#2026-07
- related_specs:
  - docs/specs/review-compatibility-hardening.md
  - docs/specs/jump-host-connection-modes.md
  - docs/specs/custom-proxy-command.md
  - docs/specs/terminal-title.md

## Problem Background

The current host node schema stores address and optional port in one `host`
string. That keeps legacy `host:port` shortcuts compact, but it creates
avoidable ambiguity for IPv6, validation, forms, imports, display formatting,
and connection planning.

The project owner has accepted a breaking config schema change and will update
local config files manually.

## Scope

- Split host endpoint storage into `host` plus optional `port` on host nodes.
- Make `host` contain only the address or hostname, never a port.
- Make `port` optional; missing or empty port means the SSH default port `22`.
- Keep IPv6 addresses unbracketed in `host`.
- Reject old combined endpoint values such as `example.com:2222` and
  `[2001:db8::1]:2222` in `host`.
- Update config validation, TUI add/edit/save, `~/.ssh/config` import, command
  planning, audit endpoint metadata, Recent fallback records, and docs.
- Keep display and command formatting responsible for adding brackets where the
  target protocol requires them.

## Non-Goals

- Do not support backward-compatible reads of old combined `host:port` values.
- Do not auto-migrate existing config files.
- Do not change the audit record shape; audit may continue to include
  `host`, `port`, and formatted `endpoint`.
- Do not change OpenSSH, Expect, SFTP, or relay handoff architecture.

## Acceptance Criteria

1. A host node with `{"host": "example.com"}` connects using port `22`.
2. A host node with `{"host": "example.com", "port": 2222}` connects using port
   `2222`.
3. A host node with `{"host": "2001:db8::1", "port": 2222}` validates and builds
   correct SSH/SFTP/SCP arguments.
4. `host` values containing combined endpoint syntax, including `host:port` and
   `[ipv6]:port`, fail validation.
5. `port` values, when present, must be numeric and in range `1..65535`.
6. TUI add/edit stores `host` and `port` as separate fields and does not combine
   them before save.
7. `~/.ssh/config` import maps `HostName` to `host` and `Port` to `port`, omitting
   `port` when OpenSSH's default `22` applies.
8. Audit and terminal title endpoint display still bracket IPv6 when a port is
   shown.
9. Existing tests are updated for the new schema and pass, except local
   `hosts.json` validation may fail until the user updates their config file.

## Technical Design

### Host Node Shape

New host nodes use:

```json
{
  "type": "host",
  "name": "prod",
  "host": "2001:db8::10",
  "port": 2222,
  "user": "deploy"
}
```

`port` may be a JSON number or string. Runtime command builders normalize it to
a string. Missing, `null`, or empty string means `22`.

### Validation

Validation should reject `host` values that contain a port separator. For IPv6,
`host` should be a raw IPv6 literal without square brackets. Brackets are only
for display and protocol-specific target strings.

### Runtime Formatting

Internal code should use a helper that returns `(host, port)` from separate node
fields. Formatting helpers continue to produce:

- `host` for port-default direct SSH target arguments when legal.
- `[ipv6]` for SFTP/scp target host forms.
- `host:port` or `[ipv6]:port` for display/audit/proxy-jump endpoints.

## Review Status

- status: approved
- verdict: PASS
- notes: Breaking schema change explicitly requested by the project owner.
