# sshgo Gap Analysis

## Metadata

- status: active
- owner: Architect
- last_reviewed: 2026-07-04
- scope: implementation risk, closed architecture gaps, optimization outcomes, and future feature candidates

## Positioning

sshgo's current design is coherent for a lightweight personal SSH manager:

- Python remains a configuration manager and launcher.
- Expect owns interactive SSH/SFTP prompt automation.
- The project stays Python-stdlib-only.
- JSONC is the only read/write configuration format.
- Runtime history and audit data stay outside `hosts.json`.

The gaps below are not accepted implementation work by themselves. Items that change behavior should become a focused spec under `docs/specs/` before implementation.

## Design Constraints

- Preserve the Expect handoff model unless a new spec explicitly changes it.
- Keep Python dependencies stdlib-only unless the roadmap changes that constraint.
- Do not silently change documented SSH, SFTP, relay, audit, or config semantics.
- Treat `proxy_command` as trusted user configuration because OpenSSH executes it locally.
- Keep current nested jump-host support limited to the direct parent model.
- Prefer small improvements that prevent mistakes or reduce daily friction; do not expand into low-frequency operations unless repeated real usage justifies the maintenance cost.

## Scope Control For A Personal Tool

Near-term work should pass at least one of these filters:

- It prevents connecting to, editing, or transferring through the wrong target.
- It makes existing daily workflows easier to diagnose.
- It catches bad config before an interactive SSH/SFTP handoff.
- It reduces code risk without changing user-facing behavior.

Common workflows should get the highest polish:

- `sshgo <alias>` should be fast, unambiguous, and hard to misuse.
- TUI browsing, search, add, and edit should give immediate feedback without corrupting terminal state.
- Upload/download should explain the selected transfer mode and fail early for unsupported inputs.
- Validation and diagnostics should produce actionable messages rather than generic failures.
- Preview output should reflect the real resolved command while redacting secrets.

The following high-maintenance ideas are intentionally out of the current plan unless the user explicitly reopens them:

- Batch multi-host commands.
- Connection health checks.
- Directory transfer support.
- Full OpenSSH config compatibility.

Other low-frequency ideas, such as final-result audit events or tags/favorites, should also stay out of active planning until repeated personal usage justifies them.

The 2026-07 safety and polish slice has closed the immediate focus items: alias safety, validation, command preview, doctor checks, TUI save-time feedback, backup recovery, command planning extraction, config storage extraction, and focused test organization. The only active implementation candidate tracked here is SFTP batch mode hardening; other future behavior changes should start as a new spec.

## Risk Register

| ID | Area | Severity | Status | Residual Risk | Direction |
|---|---|---:|---|---|---|
| R1 | CLI alias resolution | High | closed | Exact aliases are preferred and ambiguous prefixes fail before connecting. | Covered by [cli-safety-and-diagnostics](specs/cli-safety-and-diagnostics.md). |
| R2 | Jump-host topology | High | closed | Validation and runtime command builders reject unsupported deeper-than-direct host nesting. | Covered by [cli-safety-and-diagnostics](specs/cli-safety-and-diagnostics.md). |
| R3 | Remote command shortcuts | Medium | closed with documented semantics | Shortcut arguments are shell-joined safely for the interactive handoff; sshgo still does not behave as a non-interactive remote command runner. | Covered by [cli-safety-and-diagnostics](specs/cli-safety-and-diagnostics.md). |
| R4 | SFTP path and failure handling | Medium | in progress | Fragile local SFTP upload paths fail before Expect handoff. Batch-mode hardening is moving direct/tunnel SFTP success detection to OpenSSH `sftp` exit status instead of output text. | Covered by [common-workflow-polish](specs/common-workflow-polish.md); batch-mode hardening is in progress in [sftp-batch-mode-hardening](specs/sftp-batch-mode-hardening.md). |
| R5 | Audit log retention | Medium | closed | Audit trim uses lock coordination and atomic replacement; final session results remain unavailable because Python hands off with `execve`. | Covered by [config-and-audit-durability](specs/config-and-audit-durability.md). |
| R6 | HostManager scope | Medium | reduced | `HostManager` still owns domain behavior, but command planning and config storage are isolated behind focused helpers with dedicated tests. | Covered by [command-planning-extraction](specs/command-planning-extraction.md) and [config-store-extraction](specs/config-store-extraction.md). |
| R7 | Config validation depth | Medium | closed | Known top-level config fields and node candidates are validated; unknown top-level config keys remain allowed for compatibility. | Covered by [config-and-audit-durability](specs/config-and-audit-durability.md) and [common-workflow-polish](specs/common-workflow-polish.md). |
| R8 | TUI lifecycle and rendering | Low | reduced | Shared TUI templates, in-form validation, and cursor-aware field editing reduce daily friction; terminal-specific curses edge cases remain possible. | Covered by [tui-style-system](specs/tui-style-system.md), [tui-form-interaction-polish](specs/tui-form-interaction-polish.md), and [tui-input-editing-polish](specs/tui-input-editing-polish.md). |
| R9 | SSH config import fidelity | Low | accepted non-goal | `~/.ssh/config` import remains intentionally shallow. | Keep the current simple import documented; full OpenSSH config compatibility is out of the current plan. |

## Optimization Outcomes

| Outcome | Value | Spec |
|---|---|---|
| Command planning extraction | SSH/SFTP/relay launch data can be tested without patching `os.execve`. | [command-planning-extraction](specs/command-planning-extraction.md) |
| Safer alias UX | Exact aliases win and ambiguous prefixes fail before connecting. | [cli-safety-and-diagnostics](specs/cli-safety-and-diagnostics.md) |
| Validation hardening | Runtime surprises move into `--validate` and TUI save-time feedback. | [config-and-audit-durability](specs/config-and-audit-durability.md), [common-workflow-polish](specs/common-workflow-polish.md) |
| File-transfer robustness | Single-file SFTP upload rejects fragile local paths before Expect handoff. | [common-workflow-polish](specs/common-workflow-polish.md) |
| Audit durability | JSONL trim uses lock coordination and atomic replacement without changing handoff semantics. | [config-and-audit-durability](specs/config-and-audit-durability.md) |
| TUI daily-use polish | Shared templates, safer forms, delete confirmation, and cursor-aware editing improve common add/edit flows. | [tui-style-system](specs/tui-style-system.md), [tui-form-interaction-polish](specs/tui-form-interaction-polish.md), [tui-input-editing-polish](specs/tui-input-editing-polish.md) |
| Config doctor and recovery tools | Users can diagnose local setup and restore rotated config backups. | [cli-safety-and-diagnostics](specs/cli-safety-and-diagnostics.md), [config-backup-recovery](specs/config-backup-recovery.md) |
| Test suite organization | Focused modules make common workflow regressions easier to locate. | [test-suite-organization](specs/test-suite-organization.md) |

## Feature Candidates

Active implementation candidate:

- SFTP batch mode hardening: use OpenSSH `sftp -b` for direct/tunnel single-file transfers so transfer success is determined by process exit status instead of output text. See [sftp-batch-mode-hardening](specs/sftp-batch-mode-hardening.md).

Any new feature should start with a focused spec and justify its maintenance cost for a personal tool.

Deferred unless repeated real usage justifies reopening:

- Final-result audit events for SSH/SFTP/relay sessions. This would need a new design because Python currently uses `execve` and does not supervise the live session.
- Tags, favorites, or other organization metadata beyond current groups and Recent.
- Richer `~/.ssh/config` compatibility beyond the intentionally shallow import.

## Suggested Priority

1. Treat the current roadmap as complete.
2. Keep day-to-day usage stable: exact alias connection, TUI browse/search/add/edit, single-file transfer, validation, doctor, and backup recovery.
3. Only start new implementation work after a spec proves it prevents mistakes, improves a common workflow, or reduces code risk without expanding low-frequency feature surface.
