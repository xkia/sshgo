# Node identity and Recent hardening

## Metadata

- slug: node-identity-recent-hardening
- status: approved
- owner: PM/Engineer
- related_adr: none
- related_roadmap: docs/roadmap.md#2026-06
- related_specs:
  - docs/specs/config-format-jsonc.md
  - docs/specs/connection-auth-audit-hardening.md

## Product Review

Users treat a configured SSH node as a durable product object. A node rename should update the visible product experience everywhere, especially Recent. Audit logs can remain historical, but navigation surfaces should prefer the current configured node when that node still exists.

The existing `name/host/user` identity model is too weak:

- `name` changes when users rename a node.
- `host/user` can collide across different ports or purposes.
- audit history has no stable way to map a historical record to the current node.

## Scope

- Assign stable `id` values to saved host and group nodes.
- Preserve node `id` across rename and edit operations.
- Record `node_id`, `port`, and `endpoint` in new audit/history records.
- Resolve Recent entries by `node_id` first, then by legacy endpoint fields.
- Keep deleted nodes visible as read-only history snapshots.
- Add stricter configuration validation for duplicate names, duplicate IDs, invalid port ranges, and unknown node fields.
- Keep a small local backup rotation before replacing the configuration file.
- Keep the implementation dependency-free.

## Non-goals

- Rewrite existing audit history files.
- Replace Expect or manage SSH process lifecycle in Python.
- Add a database, migration framework, or external config parser.
- Change the user-facing config format away from JSONC.

## Acceptance Criteria

1. Existing configs without node IDs receive stable IDs that are saved back to JSON during normal startup or edit flows.
2. Renaming a node preserves its ID.
3. New audit history includes `node_id`, `port`, and `endpoint`.
4. Recent displays the current node name after rename when the node still exists.
5. Recent does not confuse two nodes with the same `host/user` but different ports when history contains a port.
6. Deleted nodes still appear in Recent as read-only history entries.
7. `--validate` reports duplicate node names, duplicate node IDs, invalid port ranges, and unknown node fields.
8. Saving config keeps up to three best-effort backup files beside the active JSON file.

## Technical Design

### Node IDs

Use `uuid.uuid4().hex` from the Python standard library. IDs are assigned in memory during load. `HostManager` construction is side-effect-light by default and does not persist migration changes unless callers pass `auto_migrate=True` or call `persist_node_id_migration_if_needed()`. The CLI persists pending node ID migration only for non-read-only paths such as normal startup, edit, and shortcut execution. `--validate`, `--doctor`, `--history`, and `--print-command` remain read-only and therefore do not persist migration changes. Imported `~/.ssh/config` entries remain generated runtime data and are not saved.

### Audit Identity

New audit entries include:

- `node_id`
- `host`
- `port`
- `endpoint`
- `user`

Older history records remain valid. Recent falls back to endpoint matching for legacy records.

### Recent Resolution

Recent resolution order:

1. `node_id`
2. legacy `name`
3. `host/user/port`
4. read-only history snapshot

### Config Backups

Before atomic replace, copy the current config file to backup rotation:

- `hosts.json.bak`
- `hosts.json.bak.1`
- `hosts.json.bak.2`

Backup failures are warned but do not block the primary atomic save attempt.

## Verification Plan

- Python unit tests for node ID migration, audit identity, Recent rename behavior, duplicate endpoint behavior, validation errors, and backup creation.
- Python compile check.
- `sshgo.py --validate`.
- `git diff --check`.
