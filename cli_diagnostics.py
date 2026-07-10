#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import shutil
import stat

from cli_config import load_config_snapshot
from config_store import ConfigStore
from config_validation import (
    DEFAULT_TUI_SCREEN_POLICY,
    TUI_SCREEN_POLICIES,
    merge_config,
)
from host_manager import HostManager
from i18n import i18n
from tui import Tui


def _doctor_line(status, label, detail):
    print(f"[{status}] {label}: {detail}")


def _doctor_permission_warning(path, label):
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        return
    if mode & 0o077:
        _doctor_line(
            "WARN",
            label,
            f"{path} permissions {mode:03o}; owner-only permissions are recommended",
        )


def _doctor_terminal_screen(effective_config, tui_cls=Tui):
    term = os.environ.get("TERM", "")
    if term:
        _doctor_line("PASS", "Terminal TERM", term)
    else:
        _doctor_line("WARN", "Terminal TERM", "not set")

    if tui_cls.terminal_supports_alternate_screen():
        _doctor_line("PASS", "Alternate screen", "smcup/rmcup available")
    else:
        _doctor_line(
            "WARN",
            "Alternate screen",
            "smcup/rmcup not available; TUI output may remain in terminal history",
        )

    policy = effective_config.get("tui_screen_policy", DEFAULT_TUI_SCREEN_POLICY)
    if policy == "private":
        _doctor_line(
            "WARN",
            "TUI screen policy",
            "private; exits will attempt to clear terminal scrollback",
        )
    elif not isinstance(policy, str) or policy not in TUI_SCREEN_POLICIES:
        _doctor_line("WARN", "TUI screen policy", f"invalid value: {policy}")
    else:
        _doctor_line("PASS", "TUI screen policy", policy)

    term_program = os.environ.get("TERM_PROGRAM", "")
    if term_program and "iterm" in term_program.lower() and policy == "isolated":
        _doctor_line(
            "WARN",
            "iTerm scrollback",
            "profile settings may preserve alternate-screen output",
        )


def _doctor_config_snapshot(config_path):
    return load_config_snapshot(config_path)


def _doctor_raw_config(config_snapshot):
    if not isinstance(config_snapshot, dict):
        return {}
    if isinstance(config_snapshot.get("config"), dict):
        return config_snapshot["config"]
    return config_snapshot


def _doctor_runtime_data_dir(config_snapshot, env_data_dir=None):
    if env_data_dir:
        return os.path.expanduser(env_data_dir)
    configured = _doctor_raw_config(config_snapshot).get("data_dir")
    if isinstance(configured, str) and configured:
        return os.path.expanduser(configured)
    return os.path.expanduser("~/.sshgo")


def _doctor_effective_config(config_snapshot):
    raw_config = _doctor_raw_config(config_snapshot)
    return merge_config(raw_config)


def run_doctor_for_path(
    config_path,
    data_dir=None,
    host_manager_cls=HostManager,
    tui_cls=Tui,
    which=shutil.which,
):
    data, config_errors = _doctor_config_snapshot(config_path)
    config_snapshot = (
        data.get("config", {})
        if isinstance(data, dict) and isinstance(data.get("config", {}), dict)
        else {}
    )
    lang = config_snapshot.get("language")
    if isinstance(lang, str):
        i18n.set_language(lang)

    host_manager = None
    if not config_errors:
        try:
            host_manager = host_manager_cls(
                config_path,
                data_dir=data_dir,
                auto_migrate=False,
            )
            i18n.set_language(host_manager.config.get("language", "en"))
        except SystemExit as e:
            config_errors = [
                f"{i18n.get('validate_config_invalid')}: HostManager exited with {e.code}"
            ]

    return run_doctor(
        host_manager,
        config_path,
        config_errors=config_errors,
        config_snapshot=config_snapshot,
        data_dir=data_dir,
        tui_cls=tui_cls,
        which=which,
    )


def run_doctor(host_manager, config_path, config_errors=None,
               config_snapshot=None, data_dir=None,
               tui_cls=Tui, which=shutil.which):
    failed = False

    if os.path.exists(config_path):
        _doctor_line("PASS", "Config path", config_path)
        _doctor_permission_warning(config_path, "Config permissions")
        for backup in ConfigStore.list_backups_for(config_path):
            _doctor_permission_warning(
                backup["path"],
                f"Config backup [{backup['index']}] permissions",
            )
    else:
        _doctor_line("FAIL", "Config path", f"not found: {config_path}")
        failed = True

    errors = config_errors
    if errors is None:
        errors = host_manager.validate_config()
    if errors:
        failed = True
        _doctor_line("FAIL", "Config validation", f"{len(errors)} issue(s)")
        for error in errors:
            print(f"  - {error}")
    else:
        _doctor_line("PASS", "Config validation", "ok")

    for tool in ("expect", "ssh", "sftp", "scp"):
        tool_path = which(tool)
        if tool_path:
            _doctor_line("PASS", tool, tool_path)
        else:
            _doctor_line("FAIL", tool, "not found in PATH")
            failed = True

    script_dir = os.path.dirname(os.path.realpath(__file__))
    for script in (
        "login.exp",
        "sftp_login.exp",
        "relay_transfer.exp",
        "sftp_ssh_wrapper.py",
    ):
        script_path = os.path.join(script_dir, script)
        if not os.path.exists(script_path):
            _doctor_line("FAIL", script, "missing")
            failed = True
        elif os.access(script_path, os.X_OK):
            _doctor_line("PASS", script, "present and executable")
        else:
            _doctor_line("WARN", script, "present but not executable; sshgo will try chmod")

    if host_manager is not None:
        data_dir = host_manager.audit.data_dir
        effective_config = host_manager.config
    else:
        data_dir = _doctor_runtime_data_dir(config_snapshot or {}, data_dir)
        effective_config = _doctor_effective_config(config_snapshot or {})

    _doctor_terminal_screen(effective_config, tui_cls=tui_cls)

    try:
        data_dir_exists = os.path.exists(data_dir)
        os.makedirs(data_dir, mode=0o700, exist_ok=True)
        if not data_dir_exists:
            try:
                os.chmod(data_dir, 0o700)
            except OSError:
                pass
        probe_path = os.path.join(data_dir, ".sshgo-doctor.tmp")
        with open(probe_path, "w", encoding="utf-8") as f:
            f.write("ok\n")
        os.unlink(probe_path)
        _doctor_line("PASS", "Runtime data dir", data_dir)
        _doctor_permission_warning(data_dir, "Runtime data dir permissions")
        for filename in ("history.jsonl", "audit-simple.jsonl", "audit-full.jsonl"):
            audit_path = os.path.join(data_dir, filename)
            if os.path.exists(audit_path):
                _doctor_permission_warning(audit_path, f"{filename} permissions")
    except OSError as e:
        _doctor_line("FAIL", "Runtime data dir", str(e))
        failed = True

    if os.environ.get("SSH_AUTH_SOCK"):
        _doctor_line("PASS", "SSH agent", os.environ["SSH_AUTH_SOCK"])
    elif effective_config.get("use_ssh_agent", False) is True:
        _doctor_line(
            "WARN",
            "SSH agent",
            "use_ssh_agent is enabled but SSH_AUTH_SOCK is not set",
        )
    else:
        _doctor_line("PASS", "SSH agent", "not required by global config")

    strict_host_keys = effective_config.get("strict_host_key_checking", True)
    host_key_mode = "accept-new" if strict_host_keys is not False else "no"
    if host_key_mode == "accept-new":
        _doctor_line("PASS", "Host key checking", host_key_mode)
    else:
        _doctor_line("WARN", "Host key checking", "strict checking is disabled")

    return 1 if failed else 0
