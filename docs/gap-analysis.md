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

The 2026-07 safety and polish slice has closed the immediate focus items: alias safety, validation, command preview, doctor checks, TUI save-time feedback, backup recovery, stale-write guarding, editable-only parent selection, internal module/test refactoring, TUI interaction polish, SFTP batch-mode failure handling, and the CLI-only interactive SFTP escape hatch. There is no active implementation work in this document; future behavior changes should start as a new spec.

## Risk Register

| ID | Area | Severity | Status | Residual Risk | Direction |
|---|---|---:|---|---|---|
| R1 | CLI alias resolution | High | closed | Exact aliases are preferred and ambiguous prefixes fail before connecting. | Covered by [cli-safety-and-diagnostics](specs/cli-safety-and-diagnostics.md). |
| R2 | Jump-host topology | High | closed | Validation and runtime command builders reject unsupported deeper-than-direct host nesting. | Covered by [cli-safety-and-diagnostics](specs/cli-safety-and-diagnostics.md). |
| R3 | Remote command shortcuts | Medium | closed with documented semantics | Shortcut arguments are shell-joined safely for the interactive handoff; sshgo still does not behave as a non-interactive remote command runner. | Covered by [cli-safety-and-diagnostics](specs/cli-safety-and-diagnostics.md). |
| R4 | SFTP path and failure handling | Medium | closed with manual-smoke residual | Fragile direct/tunnel SFTP paths fail before Expect handoff. Direct/tunnel SFTP now uses OpenSSH batch mode and process exit status instead of localized output text for transfer success. Real password/passphrase/MFA/tunnel environments still deserve manual smoke when changing this path. | Covered by [common-workflow-polish](specs/common-workflow-polish.md) and [sftp-batch-mode-hardening](specs/sftp-batch-mode-hardening.md). |
| R5 | Audit log retention | Medium | closed | Audit trim uses lock coordination and atomic replacement; final session results remain unavailable because Python hands off with `execve`. | Covered by [config-and-audit-durability](specs/config-and-audit-durability.md). |
| R6 | HostManager and entry-point scope | Medium | reduced | `HostManager` still owns domain behavior, but command planning, config storage, config validation, and pure host-tree operations are isolated behind focused helpers with dedicated tests. CLI diagnostics/config helper code is now outside `sshgo.py`, and stale write detection prevents older HostManager instances from silently overwriting newer config saves. | Covered by [internal-refactors-and-tests](specs/internal-refactors-and-tests.md) and [final-risk-hardening](specs/final-risk-hardening.md). |
| R7 | Config validation depth | Medium | closed | Known top-level config fields and node candidates are validated through a focused validator module; unknown top-level config keys remain allowed for compatibility. | Covered by [config-and-audit-durability](specs/config-and-audit-durability.md), [common-workflow-polish](specs/common-workflow-polish.md), and [internal-refactors-and-tests](specs/internal-refactors-and-tests.md). |
| R8 | TUI lifecycle and rendering | Low | reduced | Shared TUI templates, in-form validation, cursor-aware field editing, editable-only parent selection, and pure text/form helper modules reduce daily friction; terminal-specific curses edge cases remain possible. | Covered by [tui-interaction-polish](specs/tui-interaction-polish.md), [internal-refactors-and-tests](specs/internal-refactors-and-tests.md), and [final-risk-hardening](specs/final-risk-hardening.md). |
| R9 | SSH config import fidelity | Low | accepted non-goal | `~/.ssh/config` import remains intentionally shallow. | Keep the current simple import documented; full OpenSSH config compatibility is out of the current plan. |

## Optimization Outcomes

| Outcome | Value | Spec |
|---|---|---|
| Internal architecture cleanup | Config storage/validation, host-tree traversal, connection planning/runtime, CLI helpers, TUI helpers, and focused tests are isolated behind stable compatibility boundaries. | [internal-refactors-and-tests](specs/internal-refactors-and-tests.md) |
| Safer alias UX | Exact aliases win and ambiguous prefixes fail before connecting. | [cli-safety-and-diagnostics](specs/cli-safety-and-diagnostics.md) |
| Validation hardening | Runtime surprises move into `--validate` and TUI save-time feedback. | [config-and-audit-durability](specs/config-and-audit-durability.md), [common-workflow-polish](specs/common-workflow-polish.md) |
| File-transfer robustness | Direct/tunnel single-file SFTP rejects fragile paths before handoff and relies on OpenSSH batch-mode exit status for transfer success. | [common-workflow-polish](specs/common-workflow-polish.md), [sftp-batch-mode-hardening](specs/sftp-batch-mode-hardening.md) |
| Interactive SFTP escape hatch | `sshgo --sftp <alias>` opens a standard `sftp>` prompt for direct/tunnel hosts without expanding into a remote file manager or changing upload/download defaults. | [interactive-sftp-session](specs/interactive-sftp-session.md) |
| Audit durability | JSONL trim uses lock coordination and atomic replacement without changing handoff semantics. | [config-and-audit-durability](specs/config-and-audit-durability.md) |
| TUI daily-use polish | Shared templates, safer forms, delete confirmation, and cursor-aware editing improve common add/edit flows. | [tui-interaction-polish](specs/tui-interaction-polish.md) |
| Config doctor and recovery tools | Users can diagnose local setup and restore rotated config backups. | [cli-safety-and-diagnostics](specs/cli-safety-and-diagnostics.md), [config-backup-recovery](specs/config-backup-recovery.md) |
| Final risk hardening | Stale config saves fail instead of silently overwriting newer edits; add-parent selection only offers persisted editable nodes. | [final-risk-hardening](specs/final-risk-hardening.md) |

## Feature Candidates And Deferred Work

No active feature candidates are scheduled. Any new feature should start with a focused spec and justify its maintenance cost for a personal tool.

Deferred unless repeated real usage justifies reopening:

| Candidate | Current stance | Reopen only if |
|---|---|---|
| Batch multi-host commands | Out of current plan | Repeated usage needs show that manual loops or shell aliases are insufficient. |
| Connection health checks | Out of current plan | Connection failures become frequent enough that a diagnostic probe would materially reduce daily friction. |
| Directory transfer support | Out of current plan | Single-file upload/download is no longer enough for common workflows. |
| Full OpenSSH config compatibility | Accepted non-goal | The shallow import blocks important daily hosts and the maintenance cost is justified. |
| Final-result audit events | Deferred | A new supervision design is accepted, because Python currently uses `execve` and does not observe live session exit status. |
| Tags/favorites or richer organization metadata | Deferred | Current groups and Recent no longer cover common navigation needs. |

## Suggested Priority

1. Treat the current roadmap as complete.
2. Keep day-to-day usage stable: exact alias connection, TUI browse/search/add/edit, single-file transfer, validation, doctor, and backup recovery.
3. Only start new implementation work after a spec proves it prevents mistakes, improves a common workflow, or reduces code risk without expanding low-frequency feature surface.
