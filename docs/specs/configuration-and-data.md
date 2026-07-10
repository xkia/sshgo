# Configuration And Data

## Metadata

- slug: configuration-and-data
- status: approved
- owner: PM/Architect/Engineer
- related_roadmap: docs/roadmap.md

## Scope

This spec owns the current configuration, credential-storage, persistence,
runtime-data, audit, and Recent contracts. It replaces the completed format,
schema migration, durability, backup, identity, and credential-hardening plans.

## Configuration Format And Resolution

`hosts.json` is the only supported format. Reads accept UTF-8 JSON plus `//` and
`#` line comments and trailing commas; saves write formatted JSON. TOML, YAML,
automatic format migration, and third-party serializers are out of scope.

Config path priority is:

1. `--extra-config <path>`
2. `SSHGO_CONFIG_PATH`
3. `~/.config/sshgo/hosts.json` when present
4. the project `hosts.json`

A supplied directory resolves to its `hosts.json` child.

## Saved Schema

The root object contains `config` and `hosts`. Saved nodes are:

```json
{"id": "...", "type": "group", "name": "...", "expanded": true, "children": []}
```

```json
{
  "id": "...",
  "type": "host",
  "name": "prod",
  "host": "2001:db8::10",
  "port": 2222,
  "user": "deploy",
  "password": "...",
  "id_file": "~/.ssh/id_ed25519",
  "mfa_secret": "...",
  "use_ssh_agent": false,
  "proxy_command": "...",
  "ssh_jump_mode": "shell",
  "transfer_jump_mode": "tunnel",
  "children": []
}
```

Rules:

- `host` contains only a hostname, IPv4 address, or unbracketed IPv6 address.
  Combined `host:port` and `[ipv6]:port` values are invalid.
- `port` is optional, defaults to `22`, and must normalize to `1..65535`.
- `user` is required for hosts. Host-only fields are invalid on groups.
- A host with children is a direct-parent jump host. Deeper host nesting is
  unsupported.
- Saved host and group IDs are stable across edits. Missing IDs are assigned in
  memory and persisted only on non-read-only CLI/TUI paths.
- Duplicate names and IDs, unknown node fields, invalid field types, and invalid
  topology fail full validation.
- Runtime-only `source` metadata is never valid in persisted config. Imported SSH
  nodes and Recent snapshots are generated/read-only and are not saved.

Unknown top-level `config` keys remain tolerated for compatibility, but known
fields are type/value checked. Current known settings cover language, import,
TUI display and screen policy, audit/data directory, agent and host-key behavior,
jump/transfer defaults, relay settings, terminal titles, placeholders, and theme.

## SSH Config Import

When `config.import_ssh_config` is enabled, sshgo discovers specific non-wildcard
aliases from `~/.ssh/config` and simple `Include` patterns. It prefers `ssh -G` for
OpenSSH-resolved host, user, and port values, then falls back to the internal parser.
Relative user-config includes resolve from `~/.ssh`; recursive include loops are
ignored. `Match exec` disables the `ssh -G` path so import stays read-only. Default
identity files reported by `ssh -G` are not treated as explicit keys unless the
parsed config declared `IdentityFile`.

Imported nodes are grouped and marked as generated runtime data. They may be browsed
and connected to but are not written into `hosts.json`. Full OpenSSH matching,
canonicalization, and option compatibility remain outside the product boundary.

## Placeholders

`config.placeholders` maps names matching `[A-Za-z_][A-Za-z0-9_]*` to non-empty
strings. Expansion is one-pass, non-recursive, and occurs after JSONC parsing in:

```text
host, user, id_file, proxy_command, config.relay_temp_dir
```

Undefined or malformed placeholders fail validation. Secrets, node identity,
names, and children are never expanded. OpenSSH `%h` and `%p` tokens are left
untouched.

## Credential Ownership And Migration

`password` and `mfa_secret` are optional plaintext config values. sshgo does not
provide at-rest encryption; users own active config and backup permissions or use
keys, SSH agent, and manual prompts.

Active legacy `encryption_enabled=true` or a recognizable `v2:` credential is
rejected with migration guidance. Inactive legacy encryption metadata is accepted
for reading and removed on the next successful save. Older unprefixed ciphertext
cannot be identified safely; users must disable encryption with a pre-removal
release before upgrading.

## Validation And Read-only Paths

- `--validate` reads and validates the raw snapshot without constructing
  `HostManager`, importing SSH config, creating runtime data, assigning persisted
  IDs, prompting, or saving.
- Normal startup runs load-safety validation before tree traversal, then allows
  repairable semantic issues to be fixed through the TUI.
- Every save validates the cleaned final config before writing.
- `--history`, `--doctor`, and `--print-command` do not persist ID migrations.
- `--history` can read `SSHGO_DATA_DIR` or the default runtime directory even when
  the selected config file is absent; `--validate` still rejects a missing config.

## Persistence And Recovery

`ConfigStore` writes a same-directory temporary file, flushes it, preserves an
existing config's mode (or uses `0600` for a new file), and replaces the active file
atomically. `HostManager` passes the fingerprint of the loaded file; a mismatch fails
before backup or replacement instead of overwriting a newer edit. This is conflict
detection, not automatic merge.

Before a normal replacement, sshgo rotates backups:

```text
hosts.json.bak
hosts.json.bak.1
hosts.json.bak.2
```

`--list-backups` reports existing rotations. `--restore-backup INDEX` validates the
selected backup, preserves an existing active file in the rotation, and atomically
restores it. Restore remains available when the active config is malformed. Doctor
warns about broad permissions on the active config and every existing backup,
including backups whose primary file is missing.

## Runtime Data And Audit

Runtime directory priority is explicit constructor/CLI override (including
`SSHGO_DATA_DIR`), then `config.data_dir`, then `~/.sshgo`. The directory and new
files use owner-only permissions where POSIX modes are available and are created
lazily on append.

Files and retention limits are:

| File | Limit | Purpose |
|---|---:|---|
| `history.jsonl` | 1000 | Recent connection history |
| `audit-simple.jsonl` | 5000 | Default start and exec-failure events |
| `audit-full.jsonl` | 2000 | Optional extended launch context |

Append and trim share a per-file lock. Trim writes a temporary file and atomically
replaces the JSONL file. Records include node identity and resolved endpoint fields;
full audit may include command, path, jump, and mode context. Because Python hands
off with `execve`, these are launch records, not complete session audit.

Recent resolves history in this order: `node_id`, legacy name/endpoint fields, then
a read-only snapshot when the configured node no longer exists. Renamed live nodes
therefore retain their current name while deleted hosts remain visible historically.

## Non-goals

- No database, cloud sync, automatic merge, or unlimited version history.
- No secrets manager, Keychain integration, or custom encryption system.
- No rewrite of legacy audit records or complete session-result logging.
- No full OpenSSH configuration compatibility.

## Acceptance Criteria

1. JSONC load, strict saved-schema validation, and formatted JSON saves remain the
   only configuration lifecycle.
2. Read-only commands have no config/runtime side effects except doctor probes that
   explicitly test writability.
3. Plain secrets never become argv, preview, title, or audit-command content.
4. Atomic writes, stale-write detection, backup rotation, explicit restore, and
   owner-only permission behavior remain covered by tests.
5. Runtime logs stay outside config, retain stable node identity, and preserve the
   documented start-oriented audit boundary.

## Review Status

- status: reviewed
- verdict: PASS
- notes: Consolidates current behavior without changing runtime contracts.
