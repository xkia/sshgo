# Connection auth and audit hardening

## Metadata

- slug: connection-auth-audit-hardening
- status: approved
- owner: PM/Engineer
- related_adr: none
- related_roadmap: docs/roadmap.md#2026-06
- related_specs:
  - docs/specs/runtime-separation.md
  - docs/specs/security-hardening.md
  - docs/specs/jump-host-connection-modes.md

## Product Review

sshgo's current product shape is coherent: it is a keyboard-first SSH manager for users who want a lightweight tool without Python package dependencies. The strongest product decisions are:

- Keep Python as configuration manager and launcher, not SSH session supervisor.
- Keep Expect for interactive SSH/SFTP prompts because that is the product's core convenience.
- Standardize on JSONC to keep configuration write paths complete and dependency-free.

The main product gap is not format support. It is reliability for real-world SSH topologies:

- Jump hosts often use a different credential method than the target host.
- File transfers should be audited just like logins.
- Configuration files are important user data and should be written safely.

This change keeps the product positioning intact while improving correctness for common operational workflows.

## Scope

- Support target and jump host authentication independently for password, MFA, key, and SSH Agent decisions.
- Keep secrets out of argv and pass them only through the transient `SSHGO_*` environment copy.
- Preserve Python `execve` handoff to Expect.
- Restore terminal echo in Expect error/exit paths.
- Record SFTP transfer start/exec-failure audit events.
- Make JSON config writes atomic.
- Make audit JSONL trimming less likely to lose concurrent append records.
- Align validation with global `use_ssh_agent`.
- Clarify CLI remote command behavior in docs.

## Non-goals

- Replace Expect with Python pty.
- Record final SSH/SFTP exit code or duration.
- Implement a full SSH config parser.
- Add Python package dependencies.

## Acceptance Criteria

1. A jump host and target host can independently choose password/MFA/key/agent behavior.
2. Expect restores terminal echo on timeout, permission denied, eof, and normal exit.
3. `hosts.json` saves via atomic replace rather than direct truncating write.
4. SFTP upload/download records start and exec-failure audit entries.
5. `--validate` accepts host entries that rely on global `config.use_ssh_agent=true`.
6. Audit trimming no longer rewrites files after every append.
7. README describes `sshgo alias command...` as sending a command after login, not a non-interactive command runner.

## Technical Design

### Auth Model

HostManager computes auth material separately:

- target auth: target node + `SSH_AUTH_SOCK`
- jump auth: `nest_parent` node + `SSH_AUTH_SOCK`

Agent use is checked per node. A target may use agent while the jump host uses password/MFA, or the reverse.

For nested interactive SSH, Expect logs in to the jump host first, then starts SSH to the target from the jump host shell. This supports jump hosts that disable TCP forwarding and reject `ProxyCommand` / `ssh -W`. The full operation-mode decision is captured in [jump-host-connection-modes.md](jump-host-connection-modes.md).

For SFTP jump hosts with separate key files, Expect still constructs SFTP with `ProxyCommand` rather than plain `-J`. Nested SFTP therefore requires the jump host to allow TCP forwarding. This allows:

- outer target command to use target `-i`
- proxy jump command to use jump `-i`

### Audit

Because Python uses `execve`, audit remains start-oriented:

- `result=started`
- `result=sftp_started`
- `result=login_exp_not_found`
- `result=sftp_exp_not_found`
- `result=exec_failed:<errno>`

### Atomic Config Save

Write JSON to a temporary file in the config directory, flush/fsync it, chmod best-effort to existing file mode, then `os.replace()`.

### Audit Retention

JSONL append stays append-only during normal writes. Trimming happens only when file size by line count exceeds `max_lines + 100`, reducing rewrite frequency and concurrent write exposure.

## Verification Plan

- Python compile.
- `sshgo.py --validate`.
- Unit-style Python checks for command args, validation, atomic save, and SFTP audit exec-failure.
- Expect parser syntax smoke check where possible through `expect -n`.
