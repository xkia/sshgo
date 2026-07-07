# Terminal Title

## Metadata

- slug: terminal-title
- status: approved
- owner: PM/Architect/Engineer
- related_roadmap: docs/roadmap.md#2026-07
- related_docs:
  - docs/gap-analysis.md
- related_specs:
  - docs/specs/internal-refactors-and-tests.md
  - docs/specs/terminal-screen-policy.md
  - docs/specs/interactive-sftp-session.md

## Problem Background

When sshgo opens multiple SSH or SFTP sessions in iTerm2 or other tabbed terminals, the terminal title can remain the local shell title or project directory. That makes long-running sessions hard to distinguish and increases the risk of typing in the wrong remote tab.

sshgo already resolves the selected alias, endpoint, action, and handoff mode before replacing Python with Expect. That makes Python the right place to set a concise terminal title immediately before the SSH/SFTP/transfer handoff.

## Scope

- Add optional global config for terminal title behavior.
- Set the terminal title before interactive SSH, remote SSH command, interactive SFTP, upload/download, and relay transfer handoff.
- Reuse the existing `CommandPlan` execution path so TUI and CLI shortcuts behave consistently.
- Support title content based on alias, endpoint, or alias plus endpoint.
- Support tab title, window title, or both through standard OSC escape sequences.
- Keep the feature stdlib-only and best-effort across terminal applications.

## Non-goals

- Do not restore the previous terminal title after the remote session exits. Python is replaced by Expect through `execve()` and does not supervise the live session.
- Do not add per-host title overrides in the first version.
- Do not add arbitrary user-defined templates; keep the option set small for a personal tool.
- Do not call terminal-specific APIs such as AppleScript or iTerm2 proprietary integrations.
- Do not move title behavior into Expect scripts.
- Do not emit terminal title sequences for `--print-command`, `--validate`, `--doctor`, config editing, or TUI browsing without a handoff.

## Configuration

Add optional global config fields:

```json
{
  "config": {
    "terminal_title_enabled": false,
    "terminal_title_target": "tab",
    "terminal_title_format": "alias_host",
    "terminal_title_scope": "auto"
  }
}
```

Allowed values:

| Field | Values | Default | Behavior |
|---|---|---|---|
| `terminal_title_enabled` | `true`, `false` | `false` | Enables title output before handoff |
| `terminal_title_target` | `tab`, `window`, `both` | `tab` | Chooses OSC target: tab, window, or both |
| `terminal_title_format` | `alias`, `host`, `alias_host` | `alias_host` | Chooses title body |
| `terminal_title_scope` | `auto`, `always` | `auto` | `auto` only emits for known compatible terminal contexts; `always` emits when enabled unless stdout fails |

## Behavior

When enabled, sshgo emits one OSC title sequence immediately before recording the start audit event and calling `os.execve()`.

Title body examples:

```text
SSH prod | prod.example.com
SSH prod | prod.example.com:2222
SFTP nas | 10.0.0.8
UPLOAD nas | 10.0.0.8
RELAY DOWNLOAD app | app.internal
```

Rules:

- The mode prefix is derived from the command plan:
  - `SSH` for interactive SSH and remote SSH commands.
  - `SFTP` for interactive SFTP sessions.
  - `UPLOAD` or `DOWNLOAD` for direct/tunnel SFTP transfers.
  - `RELAY UPLOAD` or `RELAY DOWNLOAD` for relay transfers.
- Default port `22` is hidden from the title; non-default ports are shown.
- Secrets, commands, local paths, and remote paths are never included in the title.
- Control characters are stripped from title text before output.
- Terminal compatibility detection is best-effort and based on environment variables such as `TERM_PROGRAM`, `TERM`, `WT_SESSION`, and `KONSOLE_VERSION`.
- In Ghostty, `terminal_title_target: "tab"` emits `OSC 0` instead of `OSC 1` because Ghostty exposes the visible surface/tab title through the window-title sequence rather than a separate tab-title sequence.
- Title output errors are ignored so terminal behavior cannot block connection startup.

## Technical Design

### Config Validation

Add defaults and allowed sets:

```text
DEFAULT_TERMINAL_TITLE_ENABLED = false
DEFAULT_TERMINAL_TITLE_TARGET = "tab"
DEFAULT_TERMINAL_TITLE_FORMAT = "alias_host"
DEFAULT_TERMINAL_TITLE_SCOPE = "auto"
TERMINAL_TITLE_TARGETS = {"tab", "window", "both"}
TERMINAL_TITLE_FORMATS = {"alias", "host", "alias_host"}
TERMINAL_TITLE_SCOPES = {"auto", "always"}
```

Validation rules:

- `terminal_title_enabled` must be a boolean when present.
- `terminal_title_target` must be one of `tab`, `window`, or `both`.
- `terminal_title_format` must be one of `alias`, `host`, or `alias_host`.
- `terminal_title_scope` must be one of `auto` or `always`.

### Handoff Integration

`terminal_title.py` owns title formatting, terminal compatibility detection, and OSC escape emission. `HostManager._execute_command_plan()` should call this small emitter before `os.execve()` and should not keep terminal-specific formatting logic inline.

The emitter should:

1. Return immediately when `terminal_title_enabled` is false.
2. Check terminal compatibility unless scope is `always`.
3. Build the title from `plan.audit` fields that already exclude secrets.
4. Write the correct OSC sequence to stdout:
   - tab: `ESC]1;title BEL`
   - window: `ESC]2;title BEL`
   - both: `ESC]0;title BEL`
   - Ghostty tab compatibility: `tab` maps to `ESC]0;title BEL`
5. Flush stdout.
6. Swallow output errors and continue connection startup.

`--print-command` remains unaffected because it consumes command-plan args without executing the plan.

## Acceptance Criteria

1. Default config does not emit terminal title escape sequences.
2. Enabling `terminal_title_enabled` sets a tab title before SSH handoff in iTerm2-compatible environments.
3. `terminal_title_format` supports alias-only, host-only, and alias-plus-host output.
4. Default port `22` is omitted and non-default ports are shown.
5. Interactive SFTP, upload/download, and relay transfers use the correct mode prefix.
6. Invalid terminal title config values are reported by validation.
7. `--print-command` output remains unchanged.
8. Ghostty receives a title sequence that updates its visible tab/surface title when the default `tab` target is used.
9. Existing SSH, SFTP, relay, audit, and TUI screen behavior remains unchanged.

## Test Plan

- `tests/test_validation.py`
  - valid terminal title options pass validation
  - invalid terminal title options fail validation
- `tests/test_connection_auth_audit.py`
  - title output is absent by default
  - enabled title output emits the expected OSC sequence in iTerm2-style environments
  - `auto` scope skips unsupported terminal contexts
  - `always` scope emits in unsupported terminal contexts
  - SFTP and relay plans derive the expected mode prefix
- `tests/test_terminal_title.py`
  - terminal title write/flush errors are swallowed
  - C0, DEL, and C1 control characters are stripped
  - window and both OSC targets use the expected codes
  - Ghostty default tab target uses `OSC 0`
  - alias-only format and transfer mode prefixes render correctly
- `tests/test_command_plan.py`
  - command preview args remain title-free through existing plan assertions
  - enabling terminal titles does not write output when only building launch args

Use the broad verification commands in `AGENTS.md`. The focused coverage above
defines the terminal-title-specific assertions that must stay in the test suite.

## Review Status

- status: approved
- verdict: PASS
- notes: The design keeps terminal title handling optional, centralized at command handoff, and outside Expect session supervision.
