# sshgo Roadmap

## Metadata

- status: current baseline complete
- last_reviewed: 2026-07-10
- active_work: none

## Delivered Baseline

| Area | Status | Current outcome | Owner spec |
|---|---|---|---|
| Configuration and data | done | JSONC-only config, strict saved-node schema, stable IDs, atomic conflict-aware saves, three rotated backups, restore commands, runtime JSONL logs, and Recent resolution | [configuration-and-data.md](specs/configuration-and-data.md) |
| Connections and transfers | done with manual-smoke residual | Independent jump/target auth, strict host keys, shell/tunnel SSH, tunnel/relay transfer, custom proxies, batch SFTP, interactive SFTP, and optional terminal titles | [connections-and-transfers.md](specs/connections-and-transfers.md) |
| CLI and TUI | done | Ambiguity-safe aliases, safe previews, local diagnostics, save-time validation, wide-text editing, resolved details, and explicit terminal screen policy | [cli-and-tui.md](specs/cli-and-tui.md) |
| Architecture and reliability | done | Focused stdlib modules, Expect handoff, start-oriented audit, defensive validation, executable checks, and one repository verification command | [architecture-and-reliability.md](specs/architecture-and-reliability.md) |
| Documentation consolidation | done | Current behavior is owned by four domain specs; completed process records remain available through Git history | [documentation-structure.md](specs/documentation-structure.md) |

## Residual Risks

| Area | Status | Boundary |
|---|---|---|
| Real prompt variants | accepted manual-smoke risk | Fake-process coverage exercises password, passphrase, MFA, host-key, and ambiguous hop routing; real SSH/SFTP environments should be smoke-tested when these paths change. |
| Plain credentials | accepted user boundary | `password` and `mfa_secret` are plaintext in config and backups. Users protect file permissions or use keys, agent, and manual prompts. |
| Final session results | deferred by architecture | Python uses `execve` and cannot record final exit status, duration, or commands typed in interactive sessions. |
| SSH config import | accepted non-goal | Import is intentionally partial; it is not a complete OpenSSH configuration implementation. |
| Terminal behavior | accepted platform variance | Curses alternate-screen and OSC title behavior can vary by terminal; `--doctor` reports actionable local state. |
| Concurrent edits | reduced | File fingerprints prevent ordinary stale overwrites but do not provide automatic merge or multi-writer collaboration. |

## Scope Filter

New work should satisfy at least one condition:

- prevent connecting to, editing, or transferring through the wrong target;
- make an existing common workflow easier to diagnose;
- catch invalid config before SSH/SFTP handoff; or
- reduce code risk without expanding low-frequency feature surface.

## Deferred Candidates

No candidate is currently scheduled.

| Candidate | Reopen only if |
|---|---|
| Batch multi-host commands | Repeated use shows shell loops or aliases are insufficient. |
| Connection health checks | Connection failures make a network probe materially useful. |
| Directory transfer | Single-file upload/download no longer covers common workflows. |
| Full OpenSSH config compatibility | Shallow import blocks important daily hosts and justifies the maintenance cost. |
| Final-result audit events | A replacement for the current `execve` supervision boundary is accepted. |
| Tags, favorites, or richer organization | Groups and Recent no longer cover common navigation. |

Accepted behavior changes require a focused spec before implementation.
