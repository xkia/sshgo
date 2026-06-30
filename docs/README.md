# sshgo Documentation

## Core Docs

| Document | Purpose |
|---|---|
| [vision.md](vision.md) | Product goals and non-goals |
| [roadmap.md](roadmap.md) | Milestones, priorities, exit criteria, and future candidates |

## Specs

| Spec | Purpose |
|---|---|
| [config-format-jsonc.md](specs/config-format-jsonc.md) | JSONC-only config format |
| [runtime-separation.md](specs/runtime-separation.md) | Runtime data separation, history, audit, SSH agent |
| [security-hardening.md](specs/security-hardening.md) | Secret handling, host key policy, Expect handoff |
| [connection-auth-audit-hardening.md](specs/connection-auth-audit-hardening.md) | Target/jump auth independence, SFTP audit, atomic save |
| [node-identity-recent-hardening.md](specs/node-identity-recent-hardening.md) | Stable node IDs, Recent resolution, config backups |

## Documentation Rules

- `README.md` and `README.zh.md` are user-facing usage docs.
- `AGENTS.md` is the maintainer/agent implementation guide.
- `docs/specs/*.md` describe accepted behavior and implementation boundaries.
- Verification commands live in `AGENTS.md`; do not keep separate per-spec test-plan status files.
- Superseded proposals should be removed once their final decision is captured by an active spec.
