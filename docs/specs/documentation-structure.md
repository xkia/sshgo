# Documentation Structure

## Metadata

- slug: documentation-structure
- status: approved
- owner: PM/Architect
- related_roadmap: docs/roadmap.md

## Scope

Keep the repository documentation current-state focused:

- `README.md` and `README.zh.md` remain the user-facing install, usage, and
  configuration guides.
- `AGENTS.md` remains the maintainer guide for workflows, module ownership, and
  verification commands.
- `docs/README.md` owns product boundaries, the documentation index, and
  documentation maintenance rules.
- `docs/roadmap.md` owns delivery status, residual risks, and deferred candidates.
- Four domain specs own the accepted configuration/data, connection/transfer,
  CLI/TUI, and architecture/reliability contracts.
- Git history, rather than standalone Markdown files, preserves completed
  implementation plans and review chronology.

## Non-goals

- Do not change runtime behavior, configuration compatibility, or public CLI/TUI
  behavior.
- Do not remove user-facing English or Chinese documentation.
- Do not maintain duplicate module lists, test inventories, or completed test
  logs outside their single current owner.

## Consolidation Map

| Current owner | Folded content |
|---|---|
| `docs/README.md` | Product vision, goals, non-goals, and documentation rules |
| `docs/roadmap.md` | Completed milestones, active risks, and future/deferred work |
| `configuration-and-data.md` | JSONC, node schema, validation, credentials, persistence, backups, runtime logs, Recent |
| `connections-and-transfers.md` | Authentication, host keys, jump modes, proxy commands, SSH/SFTP/relay, terminal titles |
| `cli-and-tui.md` | Alias safety, preview/doctor, TUI interaction, validation feedback, screen policy |
| `architecture-and-reliability.md` | Module boundaries, handoff model, stale-write safety, compatibility constraints, verification |

## Acceptance Criteria

1. Every maintained Markdown file has one clear audience and owner.
2. Completed one-off implementation and review specs are removed after their
   durable behavior and constraints are folded into a current domain spec.
3. Product goals, current status, residual risks, and deferred candidates each
   have one source of truth.
4. All repository-local Markdown links resolve after consolidation.
5. The maintained Markdown corpus is materially smaller without dropping current
   behavior, safety boundaries, or verification entry points.
6. `./scripts/check.sh` passes because this change is documentation-only and does
   not alter accepted runtime behavior.

## Review Status

- status: reviewed
- verdict: PASS
- notes: Product boundaries and roadmap state now have single owners; 21 completed
  specs were reduced to four domain specs plus this maintenance contract. The
  maintained Markdown corpus is about 57% smaller, all local links resolve, and the
  full repository check passes 296 tests.
