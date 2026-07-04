# sshgo Roadmap

## 2026-05

| Milestone | Status | Exit Criteria | Related Spec/Doc |
|---|---|---|---|
| Runtime data separation | done | History and audit data are stored outside `hosts.json`; `--history` reads JSONL history; SSH agent config is supported | [runtime-separation](specs/runtime-separation.md) |

## 2026-06

| Milestone | Status | Exit Criteria | Related Spec/Doc |
|---|---|---|---|
| Security hardening | done with residual risks | Secrets are not passed in argv; prompt-time MFA is used; host key checking is strict by default; Python hands off with `execve` | [security-hardening](specs/security-hardening.md) |
| JSONC-only configuration | done | `hosts.json` is the only supported config format; JSONC comments/trailing commas parse; saves write JSON | [config-format-jsonc](specs/config-format-jsonc.md) |
| Connection auth and audit hardening | done | Target and jump auth are independent; SFTP is audited; config saves are atomic; audit trimming is batched | [connection-auth-audit-hardening](specs/connection-auth-audit-hardening.md) |
| Jump host connection modes | done | SSH supports `shell` and `tunnel`; transfer supports `tunnel` and `relay`; mode inheritance, validation, and real SSH/SFTP/relay chain verification are complete | [jump-host-connection-modes](specs/jump-host-connection-modes.md) |
| Node identity and Recent hardening | done | Saved nodes have stable IDs; Recent resolves renamed nodes; audit records include node identity; config backups are rotated | [node-identity-recent-hardening](specs/node-identity-recent-hardening.md) |

## 2026-07

| Milestone | Status | Exit Criteria | Related Spec/Doc |
|---|---|---|---|
| Custom ProxyCommand support | done | Direct SSH, remote-command, and direct SFTP paths can use a host-level OpenSSH ProxyCommand; global placeholders resolve in allowed connection fields without changing existing jump-host modes | [custom-proxy-command](specs/custom-proxy-command.md) |
| CLI safety and diagnostics | done | Alias ambiguity is protected; unsupported deep jump-host nesting is rejected; command preview and doctor checks are available | [cli-safety-and-diagnostics](specs/cli-safety-and-diagnostics.md) |
| Common workflow polish | done | TUI saves validate before writing; detail pane shows resolved connection state; fragile SFTP paths fail before handoff | [common-workflow-polish](specs/common-workflow-polish.md) |
| Config and audit durability | done | Known top-level config fields are validated; audit JSONL trim uses lock coordination and atomic replacement | [config-and-audit-durability](specs/config-and-audit-durability.md) |
| Config backup recovery | done | Users can list and explicitly restore rotated config backups, even when the active config is malformed | [config-backup-recovery](specs/config-backup-recovery.md) |
| Config store extraction | done | Config parsing, atomic writes, and backup storage helpers are isolated outside HostManager without behavior change | [config-store-extraction](specs/config-store-extraction.md) |
| Config validation extraction | done | Parsed-config validation helpers are isolated outside HostManager while keeping validator imports and behavior compatible | [config-validation-extraction](specs/config-validation-extraction.md) |
| Final risk hardening | done | Stale config writers fail instead of overwriting newer saves; TUI add-parent selection only offers saved editable nodes | [final-risk-hardening](specs/final-risk-hardening.md) |
| Command planning extraction | done | SSH, SFTP, and relay launch data are built through pure command-plan objects with focused tests and no behavior change | [command-planning-extraction](specs/command-planning-extraction.md) |
| Host tree extraction | done | Pure host-tree traversal, lookup, parent-link rebuilding, and node ID assignment helpers are isolated outside HostManager without behavior change | [host-tree-extraction](specs/host-tree-extraction.md) |
| TUI style system | done | Main list, forms, messages, and details use one shared TUI template without adding dependencies | [tui-style-system](specs/tui-style-system.md) |
| Terminal screen policy | done | TUI output is isolated by default, optional private mode can clear scrollback, and doctor reports terminal alternate-screen support | [terminal-screen-policy](specs/terminal-screen-policy.md) |
| TUI form interaction polish | done | Add/Edit forms use Basic/Auth/Advanced sections; validation stays in-form; delete defaults to Cancel with impact summary | [tui-form-interaction-polish](specs/tui-form-interaction-polish.md) |
| TUI input editing polish | done | Text/password fields support cursor movement, Home/End, Delete, Ctrl+U clear, and paste-friendly insertion | [tui-input-editing-polish](specs/tui-input-editing-polish.md) |
| Test suite organization | done | CommandPlan, TUI, audit, validation, CLI, and HostManager CRUD coverage move into focused test modules while keeping unittest discovery unchanged | [test-suite-organization](specs/test-suite-organization.md) |
| SFTP batch mode hardening | done | Direct/tunnel SFTP transfer success is determined by OpenSSH `sftp` batch-mode exit status rather than localized output text, while password/key/MFA prompt handling remains compatible | [sftp-batch-mode-hardening](specs/sftp-batch-mode-hardening.md) |

## Future Candidates

No active future candidates are currently scheduled. New work should first pass the personal-tool scope filters in [gap-analysis.md](gap-analysis.md), then get a focused spec under `docs/specs/`.

Explicitly out of the current plan unless repeated real usage justifies reopening:

- Batch multi-host commands.
- Connection health checks.
- Directory transfer support.
- Full OpenSSH config compatibility.
