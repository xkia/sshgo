# Credential Ownership And Reliability Hardening

## Metadata

- slug: credential-ownership-and-reliability-hardening
- status: approved
- owner: PM/Architect/Engineer
- related_roadmap: docs/roadmap.md#2026-07
- related_specs:
  - docs/specs/security-hardening.md
  - docs/specs/connection-auth-audit-hardening.md
  - docs/specs/cli-safety-and-diagnostics.md
  - docs/specs/config-and-audit-durability.md
  - docs/specs/tui-interaction-polish.md
  - docs/specs/internal-refactors-and-tests.md
- supersedes:
  - credential-encryption scope and acceptance criteria in docs/specs/security-hardening.md
  - encryption compatibility wording in docs/specs/internal-refactors-and-tests.md

## Background

sshgo is a personal launcher and connection manager. Credential-at-rest encryption
adds a second password system, custom crypto compatibility code, and backup semantics
that are not needed when the user owns credential storage and file permissions.

A project-wide review also found reliability gaps around read-only validation,
node schema enforcement, jump/target prompt routing, Expect option parsing, Unicode
TUI input, executable checks, and the maintainability of verification commands.

## Scope

- Remove sshgo-managed credential encryption and the `--toggle-encryption` command.
- Keep `password` and `mfa_secret` as optional plain string config fields whose
  storage protection is the user's responsibility.
- Reject active or recognizable encrypted credentials with an actionable migration
  error instead of treating ciphertext as a live password.
- Keep inactive legacy encryption metadata readable, but omit it on the next save.
- Make `--validate` operate directly on a raw config snapshot without constructing
  `HostManager`, importing SSH config, creating runtime data, or prompting.
- Enforce node-specific field sets and value types, including required host user,
  boolean `use_ssh_agent`, list-valued `children`, and non-empty `data_dir`.
- Validate the final cleaned config before every save.
- Route automatic password/MFA responses to the prompt's actual jump or target hop;
  ambiguous nested prompts must not consume another hop's secret.
- Parse Expect arguments as consumed option/value pairs so option-shaped values are
  preserved as values.
- Support Unicode text in main TUI search and cell-width-aware form editing.
- Avoid unconditional runtime `chmod`; report missing or non-executable handoff
  scripts through the existing execution failure path.
- Extend doctor permission checks to rotated config backups because they may contain
  the same plain credentials as the active config.
- Provide one repository verification entry point and synchronize maintained docs.

## Non-goals

- Do not migrate or decrypt legacy ciphertext in the new version.
- Do not add Keychain, secret-manager, or external crypto integration.
- Do not remove password or MFA automation from live SSH/SFTP sessions.
- Do not replace Expect, supervise live sessions in Python, add multi-hop support,
  or add Python package dependencies.
- Do not split `HostManager` or `Tui` merely to reduce line count.
- Do not change audit final-result semantics or transfer-mode behavior.

## Compatibility And Migration

- `config.encryption_enabled=true` is invalid after this change.
- Credentials beginning with the authenticated legacy prefix `v2:` are invalid.
- `encryption_enabled=false` and a null/empty `encryption_salt` are tolerated as
  inactive legacy metadata and removed on the next successful save.
- Older unprefixed XOR ciphertext cannot be distinguished reliably from a user
  string. Users of that legacy format must use the previous release to disable
  encryption before upgrading.
- The migration error must tell users to check out a pre-removal release, run
  `--toggle-encryption`, verify plaintext config, and then return to the new version.
- Rolling back to the previous release remains safe for configs saved by the new
  version because plain credentials and absent encryption metadata already mean
  encryption disabled to older releases.

## Acceptance Criteria

1. `crypto.py`, encryption defaults, encryption save/load branches, master-password
   prompts, and `--toggle-encryption` are absent from runtime and user documentation.
2. Plain password and MFA values still reach Expect only through the transient
   `SSHGO_*` environment copy and never appear in argv or command preview output.
3. Active encryption metadata or `v2:` credentials fail validation and normal
   startup with an actionable migration message.
4. `sshgo --validate` never constructs `HostManager`, never creates the runtime data
   directory, never imports `~/.ssh/config`, and returns non-zero with concise errors
   for malformed root data.
5. Normal startup reports load-unsafe structural/config-type and removed-encryption
   errors without an internal traceback or partial tree/runtime initialization, while
   still allowing semantic repairs such as deleting or renaming duplicate nodes.
6. `--history` reads the configured history path without constructing `HostManager`
   or creating a missing runtime directory.
7. Validation rejects host-only fields on groups, missing/non-string host user,
   non-string credential/path fields, non-boolean host `use_ssh_agent`, and any
   present non-list `children` value.
8. `HostManager` refuses to persist a cleaned config that fails validation.
9. A jump-host passphrase/password/MFA prompt never receives an automatically stored
   target secret, and a target prompt never receives a jump secret.
10. Direct and unambiguous shell-jump password/MFA automation remains functional;
   ambiguous tunnel prompts fall back to user interaction without secret consumption.
11. `login.exp`, `sftp_login.exp`, and `relay_transfer.exp` preserve option-shaped
   host, command, and path values and fail clearly on unknown/missing options.
12. TUI search accepts printable Unicode, and wide-character form values render and
    position the cursor by terminal cells.
13. Already-executable handoff scripts are not chmodded; missing/non-executable
    scripts produce existing audit/error behavior.
14. Doctor warns about broad permissions on the active config and every existing
    rotated backup; new config/backup files preserve owner-only defaults.
15. A single local check command runs unittest discovery, compiles all tracked Python
    files, validates the selected config, and runs `git diff --check`.
16. README, README.zh, AGENTS, vision, roadmap, gap analysis, docs index, and affected
    current behavior specs describe the post-encryption design.

## Technical Design

### Credential Ownership

Remove the crypto module and all key/salt/master-password state from `HostManager`.
Raw plain credential strings remain in memory only as required to build transient
Expect environment values. Config saves continue to use private default permissions,
atomic replacement, stale-write detection, and rotated backups.

Validation owns the removed-feature guard. It rejects active encryption and `v2:`
credential values. A small config-cleaning helper removes tolerated inactive metadata
before persistence without dropping unrelated unknown top-level config keys.

### Read-only Config Paths

Resolve config path, read JSONC, select language from the raw config object, and run
pure validation before constructing mutable/runtime services. `--validate` uses only
this path. Audit history reads should not create the runtime directory; `AuditLogger`
creates its directory lazily on append instead of in its constructor.

Normal `HostManager` startup validates a load-safety subset before tree traversal so
a bad root, node shape, known config type, or removed-encryption value cannot fail
with an internal traceback. It does not block repairable semantic issues such as
duplicate names or missing auth; `--validate` and the save invariant remain strict.

History resolves only the effective language and data directory from the validated
snapshot, then constructs a non-creating audit reader. Audit directory creation moves
to the append path.

### Node Schema And Save Invariant

Define common, group-only, and host-only saved-field sets. Validation checks raw types
before placeholder resolution or set membership. The saved host contract keeps port
as an integer or numeric string and keeps unknown top-level config keys compatible.

`HostManager._save_hosts()` cleans runtime-only fields, removes inactive encryption
metadata, validates the final plaintext data, and aborts without writing on errors.

### Prompt Routing

Replace positional password/MFA queues with `auth_response(stage, kind)`. Direct and
shell-jump modes have an explicit stage. Tunnel-mode prompt classification uses known
user/host and identity-file context. When a nested prompt cannot be classified, hand
control to the user without sending or consuming either stored secret. Relay keeps its
existing stage-aware implementation.

### Expect Arguments

Each Expect parser consumes one recognized option plus its required value per loop
iteration. Unknown options and missing values exit before secrets are read or child
processes are spawned. Values are never reprocessed as option names.

### Unicode TUI

Use wide-character input where curses exposes it. Reuse pure helpers for printable
text insertion, display-cell width, viewport selection, and cursor placement so the
stateful TUI loop remains in `Tui` and the behavior remains unit-testable.

### Runtime And Verification

Only attempt chmod when a script exists but is not executable. Keep executable
checking inside the runtime OSError handling path. Remove eager TUI chmod loops.

Add `scripts/check.sh` with a configurable `PYTHON` defaulting to `python3`. It uses
Git's tracked Python file list instead of a manually duplicated compile list.

Doctor enumerates the configured backup rotation and applies the same broad-mode
warning used for the active config. Backup behavior and restore indexes stay unchanged.

### Rollback

The implementation is delivered on an isolated branch. Before merge, rollback is
branch deletion. After merge, reverting the change restores the old command and crypto
code; configs saved by the new version remain readable as encryption-disabled plain
configs. Active legacy ciphertext must be decrypted before upgrade and is not modified
when validation rejects it.

## Verification

- Focused config, HostManager, CLI, command-plan, Expect, TUI text, and TUI tests.
- Full unittest discovery.
- Compile every tracked Python file.
- `python3 sshgo.py --validate`.
- Direct Expect preview tests for option-shaped values.
- `git diff --check`.
- Manual TUI smoke when an interactive terminal is available.

## Review Status

- status: reviewed
- verdict: PASS
- notes: The design explicitly supersedes the previous encryption behavior, preserves
  stdlib/Expect/execve constraints, fails safely on legacy ciphertext, and adds
  testable migration, rollback, permission, and read-only-path requirements.
