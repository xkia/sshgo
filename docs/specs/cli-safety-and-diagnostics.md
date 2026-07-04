# CLI safety and diagnostics

## Metadata

- slug: cli-safety-and-diagnostics
- status: approved
- owner: PM/Architect/Engineer
- related_roadmap: docs/roadmap.md#2026-07
- related_docs:
  - docs/gap-analysis.md
- related_specs:
  - docs/specs/jump-host-connection-modes.md
  - docs/specs/custom-proxy-command.md
  - docs/specs/security-hardening.md

## Background

sshgo's shortcut path is intentionally fast: `sshgo <alias>` should connect without extra ceremony. That speed should not make dangerous guesses. Current review identified several safety and diagnostics gaps:

- Prefix alias matching can silently choose one host when multiple names match.
- Deep host nesting can be accepted by validation even though current jump-host modes support only a direct parent.
- Users cannot inspect the resolved SSH/SFTP/relay command before handoff.
- Basic environment readiness checks are spread across runtime failures instead of one diagnostic command.
- Remote command shortcut arguments are joined with plain spaces, which can change shell argument boundaries.

## Scope

- Make CLI alias resolution ambiguity-safe.
- Reject unsupported deep host nesting in validation and runtime connection paths.
- Add `--print-command` to preview the resolved SSH/SFTP/relay launch command without connecting.
- Add `--doctor` to run local preflight diagnostics.
- Preserve secret handling: passwords and MFA secrets must not be printed.
- Use shell-safe joining for initial remote command shortcuts.
- Keep Python stdlib-only and preserve the Expect `execve` handoff model.

## Experience Bar

This work optimizes common paths before adding broad new features:

- `sshgo <alias>` must remain quick for exact and unique matches.
- Ambiguous input must fail before any network operation.
- Preview and doctor output must be compact enough to read in a terminal and specific enough to act on.
- Diagnostics should explain what to fix locally without requiring users to understand implementation internals.

## Non-goals

- Do not implement multi-hop jump chains.
- Do not replace Expect or supervise SSH/SFTP sessions in Python.
- Do not print or expose transient `SSHGO_*` secret environment values.
- Do not validate whether remote hosts are reachable over the network.
- Do not change TUI connection behavior except where it shares runtime validation.
- Do not add external dependencies.

## Acceptance Criteria

1. `sshgo <alias>` still accepts an exact host name match.
2. If no exact match exists and multiple host names start with the supplied alias, the command fails with an ambiguity message and candidate names.
3. If exactly one prefix match exists, existing shortcut convenience remains available.
4. `--validate` reports unsupported deeper-than-direct host nesting.
5. Runtime SSH, SFTP, and relay paths fail fast if selected nodes still contain unsupported deep host nesting.
6. `sshgo --print-command <alias>` prints the resolved sshgo-to-Expect handoff command and does not exec Expect.
7. `sshgo --print-command <alias> upload <local> <remote>` and download variants print the resolved SFTP or relay command.
8. Printed commands include resolved placeholders, jump mode, proxy command, key options, host key options, and transfer mode where applicable.
9. Printed commands do not include passwords, MFA secrets, or `SSHGO_*` environment values.
10. `sshgo --doctor` checks config validity, Expect and OpenSSH client tool availability, script presence/executability, runtime data directory writability, SSH agent state, and selected config path.
11. Remote command shortcuts use shell-safe argument joining.
12. README, README.zh, roadmap, gap analysis, and docs index mention the new accepted spec or commands.

## Technical Design

### Alias Resolution

Add a helper that returns an alias resolution object:

```text
exact match -> selected host
single prefix match -> selected host
multiple prefix matches -> ambiguous, no selected host
no match -> not found
```

The CLI shortcut handler should use this helper and print clear messages to stderr. Existing `find_host_by_alias()` can remain as a compatibility wrapper, but new CLI behavior must not silently select among multiple prefix matches.

### Jump-Depth Validation

The accepted jump-host model is a direct parent host with target host children. A host nested under a host that is itself nested under a host is unsupported.

Validation should report an error when a host depth below host parents exceeds one. Runtime command construction should also check the selected target and its parent chain before building commands, so invalid persisted configs fail even without `--validate`.

### Command Preview

`--print-command` applies to shortcut commands:

```bash
sshgo --print-command <alias>
sshgo --print-command <alias> <command...>
sshgo --print-command <alias> upload <local> <remote>
sshgo --print-command <alias> download <remote> <local>
```

Preview uses command builders that do not audit or exec:

- SSH: `HostManager.build_interactive_launch_command_args()`
- SFTP tunnel/direct: `HostManager.build_file_transfer_launch_command_args()`
- relay: `HostManager.build_file_transfer_launch_command_args()`

The rendered command should use `shlex.join()` so arguments with spaces are inspectable. The output is the resolved local handoff command that sshgo would execute, with secrets omitted from the printed environment.

### Doctor

`--doctor` should be read-only and local-only. It should report PASS/WARN/FAIL style lines for:

- config file path and existence
- config validation result
- Expect executable availability
- OpenSSH client tool availability for `ssh`, `sftp`, and `scp`
- `login.exp`, `sftp_login.exp`, `relay_transfer.exp`, and `sftp_ssh_wrapper.py` presence and executable bit
- runtime data directory creation/writability
- SSH agent environment state
- strict host key checking mode

Doctor should exit non-zero when required checks fail, such as invalid config, missing Expect, missing scripts, or unwritable runtime data directory.

### Remote Command Joining

Shortcut remote commands should preserve shell argument boundaries using `shlex.join(cmd_args[1:])`. This keeps the existing "send an initial command then interact" behavior while making argument reconstruction safer.

## Review Status

- status: reviewed
- verdict: PASS
- notes: The scope is compatible with current design constraints because it does not change the Expect handoff model, add dependencies, or implement unsupported multi-hop behavior.
