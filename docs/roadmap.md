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
| Final risk hardening | done | Stale config writers fail instead of overwriting newer saves; TUI add-parent selection only offers saved editable nodes | [final-risk-hardening](specs/final-risk-hardening.md) |
| Internal refactors and tests | done | Config storage/validation, host-tree helpers, connection planning/runtime, CLI helpers, TUI helpers, and focused tests are isolated behind stable compatibility boundaries | [internal-refactors-and-tests](specs/internal-refactors-and-tests.md) |
| TUI interaction polish | done | Main list, forms, messages, details, add/edit/delete flows, and text/password editing use shared interaction patterns without adding dependencies | [tui-interaction-polish](specs/tui-interaction-polish.md) |
| Terminal screen policy | done | TUI output is isolated by default, optional private mode can clear scrollback, and doctor reports terminal alternate-screen support | [terminal-screen-policy](specs/terminal-screen-policy.md) |
| Terminal title | done | Optional terminal tab/window titles are emitted before SSH, SFTP, transfer, and relay handoff without changing Expect supervision | [terminal-title](specs/terminal-title.md) |
| SFTP batch mode hardening | done | Direct/tunnel SFTP transfer success is determined by OpenSSH `sftp` batch-mode exit status rather than localized output text, while password/key/MFA prompt handling remains compatible | [sftp-batch-mode-hardening](specs/sftp-batch-mode-hardening.md) |
| Interactive SFTP session | done | `sshgo --sftp <alias>` opens a standard interactive `sftp>` prompt for direct/tunnel hosts, keeps `<alias> sftp` as a remote SSH command, and rejects relay before handoff | [interactive-sftp-session](specs/interactive-sftp-session.md) |
| Credential ownership and reliability hardening | done | Built-in credential encryption is removed; legacy ciphertext fails safely; read-only CLI paths stay side-effect free; config schema, Expect prompt routing/argument parsing, Unicode TUI input, executable checks, and verification are hardened | [credential-ownership-and-reliability-hardening](specs/credential-ownership-and-reliability-hardening.md) |

## Future Candidates

No active future candidates are currently scheduled.

Future-candidate boundaries and deferred/non-goal items are maintained in [gap-analysis.md](gap-analysis.md) so roadmap state has a single source of truth. New work should first pass those personal-tool scope filters, then get a focused spec under `docs/specs/`.
