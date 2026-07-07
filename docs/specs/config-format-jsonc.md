# JSONC-only configuration format

## Metadata

- slug: config-format-jsonc
- status: approved
- owner: PM
- related_roadmap: docs/roadmap.md#2026-06
- replaces: earlier TOML/YAML exploration

## Decision

sshgo should avoid additional Python package dependencies. TOML/YAML exploration was rejected because Python's standard library has no YAML support and only provides TOML reading through `tomllib`, not TOML writing.

Partial TOML support is not acceptable because users can edit hosts from the TUI and change encryption from the CLI. Any supported config format must support the full read/write lifecycle.

## Scope

- Keep `hosts.json` as the only supported configuration file.
- Keep the existing JSONC compatibility layer: `//` and `#` comments plus trailing commas.
- Remove TOML read/write support, TOML extension detection, and default `hosts.toml` probing.
- Do not add YAML support.
- Do not add Python package dependencies for configuration parsing or serialization.

## Non-goals

- Automatic migration from TOML/YAML to JSONC.
- A generic TOML writer implemented inside sshgo.
- Any change to Expect, SSH, SFTP, or session lifecycle behavior.

## Acceptance Criteria

1. `hosts.json` continues to load and validate.
2. JSONC comments and trailing commas continue to parse.
3. Saving configuration always writes JSON to the selected config path.
4. Directory config resolution uses only `hosts.json`.
5. Implementation files have no `tomllib`, `tomli_w`, `ConfigFormat`, or TOML probing path.
6. User-facing docs describe JSONC as the only supported config format.

## Technical Design

`sshgo.py` resolves the config path in this order:

1. `--extra-config <path>`
2. `SSHGO_CONFIG_PATH`
3. `~/.config/sshgo/hosts.json` when present
4. `<script_dir>/hosts.json`

If the CLI or environment path is a directory, sshgo uses `<that_dir>/hosts.json`.

`ConfigStore` reads text as UTF-8 and parses it through `config_store.parse_jsonc()`. Saves always use `json.dump(..., ensure_ascii=False, indent=4)`.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Existing users with `hosts.toml` lose direct loading support | Medium | Document JSONC as the only supported format; no automatic conversion is attempted |
| JSONC is less friendly than TOML for hand editing | Low | Comments and trailing commas are supported to reduce common JSON editing friction |
