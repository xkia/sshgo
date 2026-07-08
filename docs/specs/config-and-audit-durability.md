# Config and audit durability

## Metadata

- slug: config-and-audit-durability
- status: approved
- owner: PM/Architect/Engineer
- related_roadmap: docs/roadmap.md#2026-07
- related_docs:
  - docs/gap-analysis.md

## Background

The next highest-value personal-tool improvements are defensive rather than feature-heavy:

- catch invalid top-level config values before runtime paths use them
- make audit/history retention less likely to lose records when multiple terminals use sshgo

This keeps attention on reliability for daily workflows without adding low-frequency features.

## Scope

- Validate known top-level `config` fields for expected types.
- Validate `language`, jump-mode defaults, terminal title options, relay temp path,
  relay transfer timeout, placeholders, and supported theme colors.
- Keep unknown top-level config keys tolerated for personal notes or future compatibility.
- Make audit JSONL trim use a shared lock with append operations.
- Make trim rewrite through a temporary file and atomic replace.
- Preserve current JSONL record shape, retention limits, and stdlib-only constraints.

## Non-goals

- Do not add a new config file format.
- Do not make unknown top-level config keys fatal.
- Do not change audit record fields or add final result audit events.
- Do not replace the current `execve` handoff model.
- Do not add external dependencies.

## Acceptance Criteria

1. `validate_hosts_config()` reports invalid types for known boolean config fields.
2. `validate_hosts_config()` reports invalid `language`, `data_dir`, `encryption_salt`, and `theme` values.
3. `validate_hosts_config()` reports invalid non-negative integer config values.
4. Valid theme colors continue to pass validation.
5. Unknown top-level config keys do not fail validation.
6. Audit append and trim coordinate through the same per-file lock.
7. Trim writes the retained records through a temp file and `os.replace()`.
8. Existing retention limits remain unchanged.
9. Tests cover config schema validation and audit trimming behavior.

## Technical Design

### Config Schema

Add a small validator for known `config` keys before merged defaults are used by deeper validation. It should report only actionable type/value issues and keep unknown keys allowed.

Known booleans:

```text
encryption_enabled
import_ssh_config
show_detail_pane
audit_full
use_ssh_agent
strict_host_key_checking
show_recent
recent_expanded
terminal_title_enabled
```

Known strings:

```text
language
default_ssh_jump_mode
default_transfer_jump_mode
tui_screen_policy
terminal_title_target
terminal_title_format
terminal_title_scope
relay_temp_dir
```

Optional strings:

```text
data_dir
encryption_salt
```

Non-negative integers:

```text
relay_transfer_timeout
```

Theme keys are limited to the existing TUI color names:

```text
black, red, green, yellow, blue, magenta, cyan, white, default
```

### Audit Trim

`AuditLogger` should use a small internal lock helper around both `_append()` and `_trim()` for the same path. Append may block briefly for correctness. Trim may skip when it cannot acquire the lock, because future writes can retry trimming.

When trimming is needed, write retained lines to a temp file in the same data directory, then atomically replace the JSONL file.

## Review Status

- status: reviewed
- verdict: PASS
- notes: The change improves reliability without adding user-facing feature complexity.
