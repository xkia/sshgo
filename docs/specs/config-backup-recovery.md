# Config backup recovery

## Metadata

- slug: config-backup-recovery
- status: approved
- owner: PM/Engineer
- related_roadmap: docs/roadmap.md#2026-07
- related_specs:
  - docs/specs/node-identity-recent-hardening.md
  - docs/specs/config-and-audit-durability.md

## Background

sshgo already keeps a small `hosts.json.bak` rotation before replacing config files. Recovery currently requires users to inspect and copy those files manually. For a personal tool, backup recovery should stay small but should be available when manual edits break the active config.

## Scope

- Add a CLI command to list existing rotated config backups.
- Add a CLI command to restore one backup by index.
- Allow restore to work even when the current config is malformed.
- Validate the selected backup before replacing the active config.
- Preserve the pre-restore active config in the normal backup rotation when it exists.
- Keep the implementation stdlib-only and JSONC config behavior unchanged.

## Non-goals

- Do not add cloud sync or version history.
- Do not add an interactive restore picker.
- Do not restore runtime audit/history files.
- Do not increase backup rotation count in this change.
- Do not auto-restore without an explicit user command.

## Acceptance Criteria

1. `--list-backups` prints existing backup indexes, paths, sizes, and modified times for the resolved config path.
2. `--restore-backup INDEX` restores `hosts.json.bak` for index `0`, `hosts.json.bak.1` for index `1`, and so on.
3. Restore validates the backup data before replacing the active config.
4. Restore uses atomic replacement for the active config.
5. Restore preserves the current active config as the newest backup when it exists.
6. Restore can run when the current active config is malformed.
7. Existing tests pass, with focused coverage for listing, restore, malformed current config, and CLI output.

## Technical Design

Add static backup helpers to `HostManager` so listing and restore can run from a config path without constructing a manager around a potentially broken current config.

`sshgo.py` should resolve `--extra-config` and the default config path first, then handle `--list-backups` and `--restore-backup` before creating `HostManager`.

## Review Status

- status: reviewed
- verdict: PASS
- notes: The feature improves failure recovery without expanding high-frequency UI surface.
