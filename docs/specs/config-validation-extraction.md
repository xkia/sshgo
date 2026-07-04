# Config validation extraction

## Metadata

- slug: config-validation-extraction
- status: approved
- owner: Architect/Engineer
- related_roadmap: docs/roadmap.md#2026-07
- related_docs:
  - docs/gap-analysis.md
- related_specs:
  - docs/specs/config-and-audit-durability.md
  - docs/specs/common-workflow-polish.md
  - docs/specs/host-tree-extraction.md

## Background

`HostManager` still contains pure config validation logic even though config storage,
command planning, and host-tree helpers have already been isolated. Moving config
validation into a focused module reduces `HostManager` scope without changing the
runtime SSH/SFTP handoff model or the JSONC config contract.

## Scope

- Add a stdlib-only `config_validation.py` module for parsed `hosts.json` validation.
- Move `validate_hosts_config()` and its pure helper functions out of `host_manager.py`.
- Keep `host_manager.validate_hosts_config` import-compatible for existing callers.
- Share placeholder and jump-mode constants between validation and runtime code so
  validation behavior does not drift from runtime placeholder resolution.
- Add focused unit tests that import the validator from `config_validation.py`.
- Update architecture docs to show the new module boundary.

## Non-goals

- Do not change `hosts.json` format or JSONC parsing.
- Do not change validation rules, error messages, or unknown top-level config key
  compatibility.
- Do not change TUI add/edit validation behavior.
- Do not change SSH/SFTP/relay command planning or Expect handoff.
- Do not add dependencies.

## Acceptance Criteria

1. `config_validation.py` owns `validate_hosts_config()` and validation helper
   functions.
2. `from host_manager import validate_hosts_config` continues to work.
3. Existing validation, HostManager, TUI, and CLI tests continue to pass.
4. Focused tests cover direct `config_validation.validate_hosts_config()` usage.
5. User-visible CLI/TUI output and config write behavior remain unchanged.

## Technical Design

Keep the extracted module pure: it accepts parsed config dictionaries and returns a
list of localized validation messages. It may import `i18n`, `os`, and `re`, but it
must not read files, write files, decrypt secrets, assign node IDs, or touch audit
state.

`HostManager` should import the shared constants and validator from
`config_validation.py`. Runtime placeholder resolution should reuse the same
placeholder regex constants that validation uses.

## Review Status

- status: reviewed
- verdict: PASS
- notes: Independent review confirmed the extraction keeps validator behavior and host_manager compatibility imports intact. Node ID migration persistence is governed by node-identity-recent-hardening and is not part of this extraction.
