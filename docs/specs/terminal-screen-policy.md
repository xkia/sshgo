# Terminal Screen Policy

## Metadata

- slug: terminal-screen-policy
- status: approved
- owner: PM/Architect/Engineer
- related_roadmap: docs/roadmap.md#2026-07
- related_specs:
  - docs/specs/cli-safety-and-diagnostics.md
  - docs/specs/tui-interaction-polish.md

## Problem Background

sshgo is a curses full-screen TUI. The current implementation relies on curses and terminfo to enter the terminal alternate screen, then calls `clear`, `refresh`, and `endwin` on exit. In the standard terminal model this should behave like `vim`, `less`, or `htop`: the full-screen interface disappears and the previous shell screen is restored.

Some terminal applications, including iTerm2 when configured to retain alternate-screen output, can still preserve TUI frames in scrollback. sshgo needs an explicit terminal screen policy so the application boundary is clear: isolate sshgo's TUI output by default, but do not silently delete the user's terminal history.

## Goals

- Define sshgo's TUI screen lifecycle explicitly.
- Use an isolated full-screen TUI by default.
- Restore the normal terminal screen before quitting or handing off to SSH/Expect.
- Avoid clearing terminal scrollback by default.
- Provide an explicit privacy-oriented mode that attempts to clear the current screen and scrollback after TUI exit.
- Report terminal alternate-screen capability and active policy from `--doctor`.
- Keep Python stdlib-only.
- Preserve the current Python-to-Expect `execve` handoff model.

## Non-goals

- Do not clear scrollback by default.
- Do not attempt selective deletion of only sshgo frames from terminal history; portable terminal control sequences cannot do that reliably.
- Do not add an `inline` policy in the first version. Python curses enters the alternate screen through terminfo, and disabling that portably across macOS/ncurses variants would add compatibility risk.
- Do not change TUI layout, key bindings, connection planning, audit behavior, or live SSH/SFTP supervision.

## Configuration

Add an optional global config field:

```json
{
  "config": {
    "tui_screen_policy": "isolated"
  }
}
```

Allowed values:

```text
isolated
private
```

| Policy | Behavior |
|---|---|
| `isolated` | Default. Use the terminal alternate screen for the TUI, restore the normal screen on exit, and do not clear scrollback |
| `private` | Use `isolated`, then after returning to the normal screen, attempt to clear the current screen and scrollback |

`private` must be opt-in because it affects the whole terminal session scrollback, not only sshgo output.

## Behavior

Default `isolated` behavior:

- Starting `./sshgo.sh` opens the curses full-screen interface.
- Pressing `q` restores the normal terminal screen.
- Selecting a host restores the normal terminal screen before `execve` hands off to Expect/SSH.
- sshgo does not send the scrollback-clear sequence `ESC[3J`.
- If a terminal stores alternate-screen output in scrollback, `--doctor` explains that this is terminal-side behavior.

`private` behavior:

- TUI startup and normal restoration follow `isolated`.
- After curses cleanup returns to the normal terminal screen, sshgo writes:
  - `ESC[H`
  - `ESC[2J`
  - `ESC[3J`
- This attempts to clear the visible screen and the terminal scrollback.
- `--doctor` reports a warning that this clears the current terminal session scrollback.

When alternate-screen support is missing:

- sshgo cannot fully isolate TUI output.
- On restore, sshgo clears the current curses screen to reduce visible TUI residue.
- `--doctor` reports a warning.

## Technical Design

### Config Validation

Add:

```text
DEFAULT_TUI_SCREEN_POLICY = "isolated"
TUI_SCREEN_POLICIES = {"isolated", "private"}
```

`default_config()` includes:

```json
"tui_screen_policy": "isolated"
```

Validation rules:

- `config.tui_screen_policy` must be a string when present.
- `config.tui_screen_policy` must be one of `isolated` or `private`.

Add English and Chinese i18n strings for invalid policy validation.

### TUI Lifecycle

`Tui` should:

1. Read the effective `tui_screen_policy` from `host_manager.config`.
2. Detect whether terminfo exposes both `smcup` and `rmcup`.
3. Keep curses as the owner of full-screen setup and teardown.
4. Keep `restore_screen()` idempotent.
5. Avoid clearing the alternate screen before `endwin()` when alternate-screen support exists; `endwin()` should restore the normal screen.
6. Clear the current curses screen before `endwin()` only when alternate-screen support is missing.
7. In `private` mode, write the clear-screen and clear-scrollback escape sequence after `endwin()`.

### Doctor

`sshgo --doctor` reports:

- `TERM`
- terminal alternate-screen support based on `smcup` and `rmcup`
- active `tui_screen_policy`
- a warning for iTerm-style alternate-screen scrollback retention when applicable
- a warning for `private` mode because it clears terminal scrollback

## Acceptance Criteria

1. Default config opens the TUI in an isolated screen and restores the previous shell screen when quitting.
2. Default config does not clear terminal scrollback.
3. Selecting a host restores the normal terminal screen before Expect/SSH starts.
4. `config.tui_screen_policy = "private"` attempts to clear the visible screen and scrollback after TUI exit.
5. Invalid `tui_screen_policy` values are reported by `--validate`.
6. `--doctor` reports alternate-screen capability and the active policy.
7. Existing TUI, SSH, SFTP, relay, and audit behavior remains unchanged.

## Test Plan

- `tests/test_validation.py`
  - valid `tui_screen_policy` values pass validation
  - invalid `tui_screen_policy` values fail validation
- `tests/test_tui.py`
  - alternate-screen support avoids pre-`endwin` screen clearing
  - missing alternate-screen support clears the current screen before restore
  - `private` writes the clear-scrollback sequence after restore
  - `restore_screen()` remains idempotent
- `tests/test_cli.py`
  - doctor output includes terminal screen policy
  - doctor reports missing alternate-screen support as a warning

Use the broad verification commands in `AGENTS.md`. Also run
`python3 sshgo.py --doctor` when touching terminal-screen diagnostics or doctor
output.

## Review Status

- status: approved
- verdict: PASS
- notes: The design preserves the curses and Expect handoff model while making scrollback behavior explicit and opt-in for destructive privacy cleanup.
