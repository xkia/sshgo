# sshgo Documentation

sshgo is a lightweight personal SSH connection manager. It keeps a keyboard-first
TUI and fast CLI shortcuts while delegating protocol behavior to OpenSSH and prompt
automation to Expect. Python remains standard-library-only.

## Product Boundaries

The project optimizes safe daily connection, host management, diagnostics, and
single-file transfer. It supports password, key, SSH agent, MFA/TOTP, direct-parent
jump hosts, custom `ProxyCommand`, history, and start-oriented audit records.

It is not an SSH implementation, remote desktop, deployment system, multi-host
orchestration tool, full OpenSSH config parser, or complete session-audit service.
New features should prevent mistakes, improve a common workflow, or reduce code
risk without adding disproportionate maintenance cost.

## Maintained Documents

| Document | Audience and ownership |
|---|---|
| [`README.md`](../README.md) / [`README.zh.md`](../README.zh.md) | User installation, commands, and configuration |
| [`AGENTS.md`](../AGENTS.md) | Maintainer workflow, module ownership, architecture, and verification |
| [roadmap.md](roadmap.md) | Delivery status, residual risks, and deferred candidates |
| [configuration-and-data.md](specs/configuration-and-data.md) | Config schema, persistence, credentials, runtime data, audit, and Recent |
| [connections-and-transfers.md](specs/connections-and-transfers.md) | SSH/SFTP/relay modes, authentication, proxies, and terminal titles |
| [cli-and-tui.md](specs/cli-and-tui.md) | Shortcut safety, diagnostics, and TUI behavior |
| [architecture-and-reliability.md](specs/architecture-and-reliability.md) | Stable implementation boundaries and reliability constraints |
| [documentation-structure.md](specs/documentation-structure.md) | Documentation ownership and consolidation rules |

## Maintenance Rules

- Specs describe accepted current behavior and constraints, not implementation
  chronology. A behavior change requires updating its owning spec.
- New non-trivial work starts with a focused spec; once completed, durable facts
  are folded into the relevant domain spec and one-off plans are removed.
- Product status, residual risks, and deferred candidates live only in
  [roadmap.md](roadmap.md).
- Module inventories and verification commands live only in `AGENTS.md`.
- `README.md` and `README.zh.md` must remain behaviorally aligned.
- Git history preserves superseded proposals, review logs, and implementation
  detail that no longer belongs in maintained documentation.
