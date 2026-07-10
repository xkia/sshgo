# sshgo Documentation

## Core Docs

| Document | Purpose |
|---|---|
| [vision.md](vision.md) | Product goals and non-goals |
| [roadmap.md](roadmap.md) | Completed milestones and exit criteria |
| [gap-analysis.md](gap-analysis.md) | Current risks, closed gaps, optimization outcomes, scope filters, and future candidate boundaries |

## Current Behavior Specs

| Spec | Purpose |
|---|---|
| [config-format-jsonc.md](specs/config-format-jsonc.md) | JSONC-only config format |
| [host-port-schema-split.md](specs/host-port-schema-split.md) | Current host address plus optional port schema |
| [runtime-separation.md](specs/runtime-separation.md) | Runtime data separation, history, audit, SSH agent |
| [security-hardening.md](specs/security-hardening.md) | Secret handling, host key policy, Expect handoff |
| [credential-ownership-and-reliability-hardening.md](specs/credential-ownership-and-reliability-hardening.md) | Plain credential ownership, legacy-encryption rejection, read-only CLI paths, schema validation, prompt routing, and Unicode/runtime hardening |
| [jump-host-connection-modes.md](specs/jump-host-connection-modes.md) | Configurable SSH/transfer jump modes |
| [custom-proxy-command.md](specs/custom-proxy-command.md) | Host-level custom OpenSSH ProxyCommand and placeholders |
| [cli-safety-and-diagnostics.md](specs/cli-safety-and-diagnostics.md) | Ambiguous alias protection, command preview, doctor checks, and jump-depth validation |
| [sftp-batch-mode-hardening.md](specs/sftp-batch-mode-hardening.md) | Batch-mode SFTP transfer hardening to reduce output-text failure detection risk |
| [interactive-sftp-session.md](specs/interactive-sftp-session.md) | CLI-only interactive `sftp>` session entry point for direct/tunnel hosts |
| [terminal-screen-policy.md](specs/terminal-screen-policy.md) | TUI alternate-screen isolation and optional private scrollback cleanup |
| [terminal-title.md](specs/terminal-title.md) | Optional terminal tab/window title updates before SSH, SFTP, and transfer handoff |
| [tui-interaction-polish.md](specs/tui-interaction-polish.md) | Shared TUI style, add/edit/delete form polish, and cursor-aware text/password editing |
| [internal-refactors-and-tests.md](specs/internal-refactors-and-tests.md) | Current internal module boundaries, compatibility rules, and focused test organization |

## Historical Implementation Records

Older implementation specs may remain under `docs/specs/` only when they still
explain current edge-case rationale. Completed process logs, audit snapshots, and
superseded cleanup plans should be deleted or folded into `gap-analysis.md` and
the current behavior specs.

## Documentation Rules

- `README.md` and `README.zh.md` are user-facing usage docs.
- `AGENTS.md` is the maintainer/agent implementation guide.
- `docs/gap-analysis.md` tracks active risks, closed gaps, optimization outcomes, and future candidate boundaries; items there are not accepted behavior until captured by a spec or roadmap milestone.
- `docs/roadmap.md` tracks completed milestones and should point to `gap-analysis.md` for future-candidate boundaries instead of duplicating them.
- `docs/specs/*.md` normally describe accepted behavior and implementation boundaries; files marked `status: proposed` or `status: in_progress` are not completed behavior until the roadmap/review status says so.
- Verification commands live in `AGENTS.md`; do not keep separate per-spec test-plan status files.
- Superseded proposals or sections should be removed when they no longer add useful context. Historical context may remain only when it is clearly marked as superseded and points to the active replacement spec.
