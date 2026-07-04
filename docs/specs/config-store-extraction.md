# Config store extraction

## Metadata

- slug: config-store-extraction
- status: approved
- owner: Architect/Engineer
- related_roadmap: docs/roadmap.md#2026-07
- related_docs:
  - docs/gap-analysis.md
- related_specs:
  - docs/specs/config-format-jsonc.md
  - docs/specs/config-and-audit-durability.md
  - docs/specs/config-backup-recovery.md

## Background

`HostManager` still owns config file parsing, atomic writes, backup rotation, backup recovery, node CRUD, validation, encryption, audit planning, and command launch behavior. Command planning has already been isolated. The next low-risk split is the file storage layer.

## Scope

- Add a stdlib-only `ConfigStore` module for JSONC parsing, config reads, atomic JSON writes, backup rotation, backup listing, and backup restore.
- Keep `HostManager` as the owner of config semantics, encryption/decryption, migration, validation calls, node CRUD, and runtime behavior.
- Preserve existing public helper methods on `HostManager` as compatibility wrappers where they already exist.
- Preserve backup file names and rotation count.

## Non-goals

- Do not change the `hosts.json` format.
- Do not add a database or new config format.
- Do not change encryption behavior.
- Do not change validation rules.
- Do not change CLI command names or backup recovery behavior.

## Acceptance Criteria

1. Config JSONC parsing lives in `config_store.py`.
2. Atomic write and backup rotation live in `config_store.py`.
3. Backup listing and restore live in `config_store.py`.
4. `HostManager` delegates config read/write/backup operations to `ConfigStore`.
5. Existing `HostManager.list_config_backups()` and `HostManager.restore_config_backup()` still work.
6. Existing tests pass, with focused coverage for `ConfigStore`.

## Technical Design

`ConfigStore` should hold only a config path and file-level helpers:

- `read()`
- `write_json(data)`
- `backup_path(index)`
- `list_backups()`
- `restore_backup(index, validate_func=None)`

Static/class helpers may support CLI use before `HostManager` is constructed.

`HostManager` should instantiate `self.store = ConfigStore(config_path)` and keep `self.json_path` for compatibility.

## Review Status

- status: reviewed
- verdict: PASS
- notes: This isolates storage concerns without changing user-visible config behavior.
