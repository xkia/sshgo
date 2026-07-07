# Review Compatibility Hardening

## Metadata

- slug: review-compatibility-hardening
- status: approved
- owner: PM/Architect/Engineer
- related_roadmap: docs/roadmap.md#2026-07
- related_docs:
  - docs/gap-analysis.md
- related_specs:
  - docs/specs/cli-safety-and-diagnostics.md
  - docs/specs/config-and-audit-durability.md
  - docs/specs/security-hardening.md
  - docs/specs/jump-host-connection-modes.md
  - docs/specs/terminal-title.md

## Supersession Note

Endpoint storage behavior in the original version of this spec was superseded
by `docs/specs/host-port-schema-split.md`. Current host nodes store address and
port separately, and no longer accept combined `host:port` config values. The
remaining active scope of this spec is diagnostics, permissions, SSH config
import hardening, TUI text width, host-key wording, and Expect prompt
compatibility.

## Problem Background

A project-wide review found several compatibility and robustness gaps in otherwise working core flows:

- Earlier endpoint parsing rejected or misparsed IPv6 host values because host
  and port were split on the first colon. Current endpoint storage is governed
  by `host-port-schema-split.md`.
- Interactive SSH and relay shell paths depend on narrow shell prompt regexes.
- `--doctor` may prompt for a master password on encrypted configs, making diagnostics less script-friendly.
- Invalid encryption salt values pass validation but fail during normal load/save.
- Config, audit, and history files can retain or inherit broad permissions.
- `~/.ssh/config` import handles only a small subset of OpenSSH syntax.
- TUI text truncation uses character count instead of terminal cell width.
- Host-key detail wording is ambiguous for shell jump targets.

## Scope

- Use the current host/port schema split for endpoint storage and formatting.
- Make config validation reject invalid encrypted salt values.
- Make `--doctor` remain read-only and non-interactive for valid encrypted configs.
- Create runtime audit/history data with private permissions and warn on broad config/runtime permissions in `--doctor`.
- Improve `~/.ssh/config` import by using `ssh -G` when available and falling back to the current parser.
- Add display-width aware TUI ellipsizing for CJK/wide characters.
- Clarify shell jump host-key display wording.
- Improve Expect prompt compatibility without replacing the current Expect handoff model.

## Non-Goals

- Do not replace Expect with Python pty.
- Do not add Python package dependencies.
- Do not change the top-level `hosts.json` schema.
- Do not add multi-hop jump-host support.
- Do not make relay transfers directory-aware.
- Do not record SSH/SFTP final exit status from Python.

## Acceptance Criteria

1. Endpoint storage and validation follow `host-port-schema-split.md`.
2. TUI add/edit and `~/.ssh/config` import preserve IPv6 host and port as separate values.
3. Terminal title and audit endpoint formatting bracket IPv6 when a port is shown.
4. `--validate` reports malformed `encryption_salt` before normal startup can crash on base64 decoding.
5. `sshgo --doctor` does not prompt for the master password solely to report local diagnostics.
6. Runtime data directory and audit/history files are created with private permissions where the platform supports POSIX modes.
7. `--doctor` warns when config or runtime data permissions are broader than owner-only.
8. TUI ellipsizing respects wide characters better than raw `len()` slicing.
9. Shell jump detail output makes clear that target host-key state is managed on the jump host.
10. Existing unit tests, py_compile, config validation, and diff whitespace checks pass.

## Technical Design

### Endpoint Handling

Superseded by `host-port-schema-split.md`. Current config uses `host` for the
bare hostname/address and optional `port` for the numeric SSH port. Formatting
helpers may still produce `host:port` or `[ipv6]:port` for display, audit, and
OpenSSH target syntax.

### Diagnostics and Permissions

`--doctor` should validate the raw config snapshot and report local preflight state without constructing `HostManager` when the config is encrypted. It can derive effective config values from merged defaults and the raw snapshot.

Runtime data directory should be `0700` when created, and audit/history files should be `0600` when created. Existing broader files should not be destructively rewritten during doctor; doctor should warn.

### Salt Validation

Validation should accept `None` or valid URL-safe base64 salt bytes when `encryption_salt` is present. When encryption is enabled and credentials exist, missing or malformed salt should be reported as a config error.

### SSH Config Import

Prefer `ssh -G <alias>` for specific non-wildcard aliases because OpenSSH can resolve quoting, defaults, and canonicalized options. The alias discovery pass should also follow simple `Include` patterns so aliases defined outside the root `~/.ssh/config` can be offered for import; relative user-config includes are resolved from `~/.ssh`, matching OpenSSH behavior. Keep the current parser as a fallback when `ssh -G` fails, do not treat OpenSSH's default `identityfile` output as an explicit sshgo key unless the parsed config declared `IdentityFile`, and skip the `ssh -G` path when `Match exec` is present so import remains read-only.

### Expect Prompt Compatibility

Keep Expect as the runtime handoff tool. Broaden prompt detection to include common prompt glyphs such as `❯`, and when authentication prompts are complete but no prompt pattern appears before timeout, hand off to `interact` for interactive SSH rather than failing immediately. Remote-command execution may still rely on prompt matching.

## Review Status

- status: approved
- verdict: PASS
- notes: This spec implements the compatibility fixes requested after the project-wide review while preserving existing architecture constraints.
