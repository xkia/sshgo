# Architecture And Reliability

## Metadata

- slug: architecture-and-reliability
- status: approved
- owner: Architect/Engineer
- related_roadmap: docs/roadmap.md

## Scope

This spec owns stable implementation boundaries and cross-cutting reliability
constraints. The exact module inventory and verification commands remain in
`AGENTS.md`; this document records the contracts that should survive refactors.

## Architecture Boundaries

- `sshgo.sh` is a thin path-resolving wrapper; `sshgo.py` is the single Python entry
  point and owns argument parsing, high-level dispatch, shortcuts, and TUI launch.
- `HostManager` remains the public facade for config lifecycle, CRUD, validation,
  alias resolution, descriptions, preview, and execution entry points.
- Config storage, validation, tree traversal, and CRUD mutation live in focused
  modules. Pure validation and tree helpers must not acquire runtime side effects.
- `ConnectionPlanner` builds SSH, SFTP, interactive SFTP, and relay `CommandPlan`
  values through a narrow structural adapter and must not import `host_manager.py`.
- `ConnectionRuntime` owns executable checks, secret-environment construction,
  optional title emission, audit start/failure records, and `os.execve()` handoff.
- Expect scripts own prompt automation and live OpenSSH interaction. Python does not
  become an SSH/SFTP protocol client or session supervisor.
- Stateful curses lifecycle remains in `Tui`; rendering, Recent, CRUD orchestration,
  text editing, and form conversion use focused helpers where behavior is pure.

## Reliability Invariants

- Python remains standard-library-only; runtime external tools are Expect and the
  OpenSSH clients `ssh`, `sftp`, and `scp`.
- Config is validated before unsafe traversal and again in complete form before
  persistence. Writes use locking, atomic replacement, backup rotation, and optional
  stale-fingerprint checks.
- Runtime history/audit files are append-oriented, owner-private where supported,
  lock-coordinated during trim, and separate from config.
- Credentials cross the Python-to-Expect boundary only in a transient environment
  copy. Command plans, argv, previews, titles, and audit command fields are
  secret-free.
- Handoff scripts are checked at execution time. Existing executable files are not
  chmodded; a present non-executable script may be made executable, while missing or
  failed handoffs use the normal localized/audit error path.
- UTF-8 locale normalization applies only to the child environment needed for Expect
  and does not mutate unrelated process state.
- Saved/generated node boundaries remain explicit: imported SSH nodes and Recent
  snapshots are browseable but not persisted or selected as editable parents.
- Every user-facing string added to runtime code is represented in both English and
  Chinese dictionaries.

## Compatibility Constraints

Refactors must preserve:

- JSONC-only config and the documented config-path priority;
- direct-parent jump topology and `shell`/`tunnel`/`relay` semantics;
- independent target/jump auth and boundary-aware ambiguous-prompt fallback;
- safe command previews and start-oriented audit semantics;
- TUI key bindings, validation feedback, screen restoration, and read-only Recent;
- stdlib/unittest tooling and the shell wrapper's caller working directory.

Compatibility wrappers or re-exports should not remain solely for a completed
refactor. Tests and internal code should import definitions from their owning module,
while public CLI/TUI calls continue through the facade.

## Explicit Non-goals

- No package-directory conversion, dependency framework, database, or alternate test
  runner without a focused spec.
- No Expect rewrite, Python live-session supervision, multi-hop expansion, or final
  session audit as incidental refactoring.
- No automatic merge for concurrent config writers.
- No splitting stateful TUI or Expect code for aesthetics or line-count targets.

## Verification Contract

`AGENTS.md` is the command source of truth. Broad changes run the repository check,
which performs unittest discovery, compiles tracked Python files, validates the
tracked minimal config fixture, and checks diff whitespace. Narrow changes may run a
focused subset first but must preserve the broad check. Terminal-specific TUI or real
SSH/SFTP behavior is reported separately when an interactive environment is not
available.

## Acceptance Criteria

1. Public behavior changes are rejected from refactor-only work unless an owning
   domain spec is updated.
2. Planning, runtime execution, persistence, validation, and TUI state retain clear
   ownership and focused tests.
3. Failures occur before destructive writes or network handoff where the local state
   is already known to be invalid.
4. One deterministic clean-clone verification entry point remains sufficient for
   repository-wide automated checks.

## Review Status

- status: reviewed
- verdict: PASS
- notes: Consolidates current module and reliability contracts; detailed inventories
  remain in `AGENTS.md` to avoid duplication.
