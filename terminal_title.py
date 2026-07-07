#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys

from config_validation import (
    DEFAULT_PORT,
    DEFAULT_TERMINAL_TITLE_FORMAT,
    DEFAULT_TERMINAL_TITLE_SCOPE,
    DEFAULT_TERMINAL_TITLE_TARGET,
    TERMINAL_TITLE_FORMATS,
    TERMINAL_TITLE_SCOPES,
    TERMINAL_TITLE_TARGETS,
)
from endpoint import format_endpoint

OSC_CODES = {
    "tab": "1",
    "window": "2",
    "both": "0",
}
COMPATIBLE_TERM_PROGRAMS = frozenset({
    "apple_terminal",
    "ghostty",
    "hyper",
    "iterm.app",
    "vscode",
    "warpterminal",
    "wezterm",
})
COMPATIBLE_TERM_MARKERS = (
    "alacritty",
    "kitty",
    "rxvt",
    "screen",
    "tmux",
    "wezterm",
    "xterm",
)


def emit_terminal_title(
    config,
    plan,
    env=None,
    output=None,
    output_is_tty=None,
):
    if not should_emit_terminal_title(config, env=env, output_is_tty=output_is_tty):
        return False

    if output is None:
        output = sys.stdout
    code = terminal_title_target_code(config, env=env)
    title = terminal_title_for_plan(config, plan)
    try:
        output.write(f"\033]{code};{title}\007")
        output.flush()
    except (OSError, UnicodeError, ValueError):
        return False
    return True


def should_emit_terminal_title(config, env=None, output_is_tty=None):
    if config.get("terminal_title_enabled") is not True:
        return False
    if terminal_title_scope(config) == "always":
        return True
    if env is None:
        env = os.environ
    return terminal_title_supported(env, output_is_tty=output_is_tty)


def terminal_title_scope(config):
    scope = config.get("terminal_title_scope", DEFAULT_TERMINAL_TITLE_SCOPE)
    if scope not in TERMINAL_TITLE_SCOPES:
        return DEFAULT_TERMINAL_TITLE_SCOPE
    return scope


def terminal_title_supported(env, output_is_tty=None):
    if not _output_is_tty(output_is_tty):
        return False
    if env.get("CI") or env.get("TERM") == "dumb":
        return False

    term_program = env.get("TERM_PROGRAM", "").lower()
    if term_program in COMPATIBLE_TERM_PROGRAMS or terminal_title_ghostty(env):
        return True

    if env.get("WT_SESSION") or env.get("KONSOLE_VERSION"):
        return True

    term = env.get("TERM", "").lower()
    return any(marker in term for marker in COMPATIBLE_TERM_MARKERS)


def terminal_title_target_code(config, env=None):
    target = config.get("terminal_title_target", DEFAULT_TERMINAL_TITLE_TARGET)
    if target not in TERMINAL_TITLE_TARGETS:
        target = DEFAULT_TERMINAL_TITLE_TARGET
    if target == "tab" and terminal_title_ghostty(env):
        return OSC_CODES["both"]
    return OSC_CODES[target]


def terminal_title_ghostty(env=None):
    if env is None:
        env = os.environ
    term_program = env.get("TERM_PROGRAM", "").lower()
    term = env.get("TERM", "").lower()
    return (
        term_program == "ghostty"
        or "ghostty" in term
        or bool(env.get("GHOSTTY_RESOURCES_DIR"))
        or bool(env.get("GHOSTTY_BIN_DIR"))
    )


def terminal_title_format(config):
    title_format = config.get(
        "terminal_title_format",
        DEFAULT_TERMINAL_TITLE_FORMAT,
    )
    if title_format not in TERMINAL_TITLE_FORMATS:
        return DEFAULT_TERMINAL_TITLE_FORMAT
    return title_format


def terminal_title_for_plan(config, plan):
    mode = terminal_title_mode(plan)
    body = terminal_title_body(config, plan.audit)
    title = f"{mode} {body}" if body else mode
    return sanitize_terminal_title(title)


def terminal_title_mode(plan):
    if plan.start_result == "started":
        return "SSH"
    if plan.start_result == "sftp_interactive_started":
        return "SFTP"

    command = str(plan.audit.get("command") or "")
    action = command.split(" ", 1)[0].lower()
    if action in ("upload", "download"):
        prefix = "RELAY " if plan.start_result.startswith("relay_") else ""
        return f"{prefix}{action.upper()}"
    return "SSH"


def terminal_title_body(config, audit):
    name = str(audit.get("name") or "")
    endpoint = terminal_title_endpoint(audit)
    title_format = terminal_title_format(config)

    if title_format == "alias":
        return name or endpoint
    if title_format == "host":
        return endpoint or name
    if name and endpoint and name != endpoint:
        return f"{name} | {endpoint}"
    return name or endpoint


def terminal_title_endpoint(audit):
    host = str(audit.get("host") or "")
    port = str(audit.get("port") or "")
    if host:
        return format_endpoint(
            host,
            port or DEFAULT_PORT,
            default_port=DEFAULT_PORT,
            include_default=False,
        )
    return str(audit.get("endpoint") or "")


def sanitize_terminal_title(value):
    return "".join(
        ch
        for ch in str(value)
        if ord(ch) >= 32 and not 0x7F <= ord(ch) <= 0x9F
    )


def _output_is_tty(output_is_tty=None):
    if output_is_tty is not None:
        return bool(output_is_tty())
    isatty = getattr(sys.stdout, "isatty", None)
    return bool(isatty and isatty())
