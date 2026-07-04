# sshgo Documentation

## Core Docs

| Document | Purpose |
|---|---|
| [vision.md](vision.md) | Product goals and non-goals |
| [roadmap.md](roadmap.md) | Milestones, priorities, exit criteria, and future candidates |
| [gap-analysis.md](gap-analysis.md) | Current risks, closed gaps, optimization outcomes, and future candidate boundaries |

## Specs

| Spec | Purpose |
|---|---|
| [config-format-jsonc.md](specs/config-format-jsonc.md) | JSONC-only config format |
| [runtime-separation.md](specs/runtime-separation.md) | Runtime data separation, history, audit, SSH agent |
| [security-hardening.md](specs/security-hardening.md) | Secret handling, host key policy, Expect handoff |
| [connection-auth-audit-hardening.md](specs/connection-auth-audit-hardening.md) | Target/jump auth independence, SFTP audit, atomic save |
| [jump-host-connection-modes.md](specs/jump-host-connection-modes.md) | Configurable SSH/transfer jump modes |
| [node-identity-recent-hardening.md](specs/node-identity-recent-hardening.md) | Stable node IDs, Recent resolution, config backups |
| [custom-proxy-command.md](specs/custom-proxy-command.md) | Host-level custom OpenSSH ProxyCommand and placeholders |
| [cli-safety-and-diagnostics.md](specs/cli-safety-and-diagnostics.md) | Ambiguous alias protection, command preview, doctor checks, and jump-depth validation |
| [common-workflow-polish.md](specs/common-workflow-polish.md) | TUI save validation, richer details, and safer SFTP path handling |
| [config-and-audit-durability.md](specs/config-and-audit-durability.md) | Top-level config validation and safer audit trim |
| [config-backup-recovery.md](specs/config-backup-recovery.md) | List and restore rotated config backups |
| [config-store-extraction.md](specs/config-store-extraction.md) | Isolated config file parsing, atomic writes, and backup storage helpers |
| [config-validation-extraction.md](specs/config-validation-extraction.md) | Isolated parsed-config validation helpers with HostManager compatibility export |
| [final-risk-hardening.md](specs/final-risk-hardening.md) | Stale config write guard and editable-only TUI parent selection |
| [tui-style-system.md](specs/tui-style-system.md) | Shared TUI layout, form, message, and detail templates |
| [tui-form-interaction-polish.md](specs/tui-form-interaction-polish.md) | Add/Edit/Delete form grouping, in-form validation, and safer delete confirmation |
| [tui-input-editing-polish.md](specs/tui-input-editing-polish.md) | Cursor-aware text/password editing for TUI forms |
| [command-planning-extraction.md](specs/command-planning-extraction.md) | Pure SSH/SFTP/relay command plan objects for safer launch testing |
| [host-tree-extraction.md](specs/host-tree-extraction.md) | Pure host tree helpers for traversal, lookup, parent links, and node ID assignment |
| [test-suite-organization.md](specs/test-suite-organization.md) | Focused test modules for isolated implementation areas |
| [sftp-batch-mode-hardening.md](specs/sftp-batch-mode-hardening.md) | Batch-mode SFTP transfer hardening to reduce output-text failure detection risk |

## Documentation Rules

- `README.md` and `README.zh.md` are user-facing usage docs.
- `AGENTS.md` is the maintainer/agent implementation guide.
- `docs/gap-analysis.md` tracks active risks, closed gaps, optimization outcomes, and future candidate boundaries; items there are not accepted behavior until captured by a spec or roadmap milestone.
- `docs/specs/*.md` normally describe accepted behavior and implementation boundaries; files marked `status: proposed` or `status: in_progress` are not completed behavior until the roadmap/review status says so.
- Verification commands live in `AGENTS.md`; do not keep separate per-spec test-plan status files.
- Superseded proposals should be removed once their final decision is captured by an active spec.
