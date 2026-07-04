#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
from dataclasses import dataclass

SECRET_ENV_KEYS = {
    "target_pass": "SSHGO_TARGET_PASS",
    "jumper_pass": "SSHGO_JUMPER_PASS",
    "mfa_secret": "SSHGO_MFA_SECRET",
    "jumper_mfa_secret": "SSHGO_JUMPER_MFA_SECRET",
}
SECRET_ENV_VAR_NAMES = frozenset(SECRET_ENV_KEYS.values())
UTF8_LOCALE_FALLBACK = "en_US.UTF-8" if sys.platform == "darwin" else "C.UTF-8"


@dataclass(frozen=True)
class CommandPlan:
    script_path: str
    args: tuple
    secret_env: dict
    audit: dict
    start_result: str
    missing_result: str
    exec_failed_prefix: str
    missing_message: str = ""
    exec_error_message: str = ""

    def launch_args(self):
        return [self.script_path] + list(self.args)


def secret_env_values(secrets):
    values = {}
    for key, env_key in SECRET_ENV_KEYS.items():
        value = secrets.get(key)
        if value:
            values[env_key] = str(value)
    return values


def env_for_secret_values(secret_env, base_env=None):
    env = dict(os.environ if base_env is None else base_env)
    for env_key in SECRET_ENV_VAR_NAMES:
        env.pop(env_key, None)
    ensure_utf8_locale(env)
    env.update(secret_env)
    return env


def env_for_plan(plan, base_env=None):
    return env_for_secret_values(plan.secret_env, base_env=base_env)


def ensure_utf8_locale(env):
    candidates = [
        env.get("LC_ALL", ""),
        env.get("LC_CTYPE", ""),
        env.get("LANG", ""),
    ]
    utf8_locale = next(
        (
            value
            for value in candidates
            if isinstance(value, str)
            and ("UTF-8" in value.upper() or "UTF8" in value.upper())
        ),
        UTF8_LOCALE_FALLBACK,
    )
    if not env.get("LANG") or not (
        "UTF-8" in env.get("LANG", "").upper()
        or "UTF8" in env.get("LANG", "").upper()
    ):
        env["LANG"] = utf8_locale
    if not env.get("LC_CTYPE") or not (
        "UTF-8" in env.get("LC_CTYPE", "").upper()
        or "UTF8" in env.get("LC_CTYPE", "").upper()
    ):
        env["LC_CTYPE"] = utf8_locale
    if env.get("LC_ALL") and not (
        "UTF-8" in env.get("LC_ALL", "").upper()
        or "UTF8" in env.get("LC_ALL", "").upper()
    ):
        env["LC_ALL"] = utf8_locale
