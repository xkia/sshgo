# sshgo Roadmap

## 2026-05

| Milestone | Status | Exit Criteria | Related Spec |
|---|---|---|---|
| Runtime data separation | done | History and audit data are stored outside `hosts.json`; `--history` reads JSONL history; SSH agent config is supported | [runtime-separation](specs/runtime-separation.md) |

## 2026-06

| Milestone | Status | Exit Criteria | Related Spec |
|---|---|---|---|
| Security hardening | done with residual risks | Secrets are not passed in argv; prompt-time MFA is used; host key checking is strict by default; Python hands off with `execve` | [security-hardening](specs/security-hardening.md) |
| JSONC-only configuration | done | `hosts.json` is the only supported config format; JSONC comments/trailing commas parse; saves write JSON | [config-format-jsonc](specs/config-format-jsonc.md) |
| Connection auth and audit hardening | done | Target and jump auth are independent; SFTP is audited; config saves are atomic; audit trimming is batched | [connection-auth-audit-hardening](specs/connection-auth-audit-hardening.md) |
| Node identity and Recent hardening | done | Saved nodes have stable IDs; Recent resolves renamed nodes; audit records include node identity; config backups are rotated | [node-identity-recent-hardening](specs/node-identity-recent-hardening.md) |

## Future Candidates

| Milestone | Status | Exit Criteria | Related Spec |
|---|---|---|---|
| Batch operations and multi-host commands | unscheduled | A spec defines command fan-out semantics, failure handling, output grouping, and audit behavior | - |
| Connection health checks | unscheduled | A spec defines lightweight reachability checks, UI surfacing, timeout behavior, and audit impact | - |
