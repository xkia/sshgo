#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import glob
import shlex
import subprocess
import sys


class SshConfigParser:
    def _append_param(self, params, key, value):
        existing = params.get(key)
        if existing is None:
            params[key] = value
        elif isinstance(existing, list):
            existing.append(value)
        else:
            params[key] = [existing, value]

    def _param_values(self, params, key):
        value = params.get(key)
        if value is None:
            return []
        if isinstance(value, list):
            return [item for item in value if item]
        return [value] if value else []

    def _param_first(self, params, key, default=""):
        values = self._param_values(params, key)
        return values[0] if values else default

    def _include_paths(self, config_root, patterns):
        paths = []
        for pattern in patterns:
            expanded = os.path.expanduser(pattern)
            if not os.path.isabs(expanded):
                expanded = os.path.join(config_root, expanded)
            paths.extend(sorted(glob.glob(expanded)))
        return paths

    def _match_exec_present(self, line):
        try:
            parts = shlex.split(line, comments=True)
        except ValueError:
            return False
        return bool(parts and parts[0].lower() == "match" and "exec" in (
            part.lower() for part in parts[1:]
        ))

    def _parse_config_file(self, config_path, state, active_files, config_root):
        config_path = os.path.realpath(os.path.expanduser(config_path))
        if config_path in active_files:
            return
        active_files.add(config_path)

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    if self._match_exec_present(line):
                        self._ssh_g_safe = False
                        if state["current_host_block"]:
                            state["all_hosts_data"].append(
                                state["current_host_block"]
                            )
                            state["current_host_block"] = None
                        continue

                    if line.lower().startswith("include "):
                        include_patterns = shlex.split(
                            line[8:].strip(),
                            comments=True,
                        )
                        for include_path in self._include_paths(
                            config_root,
                            include_patterns,
                        ):
                            self._parse_config_file(
                                include_path,
                                state,
                                active_files,
                                config_root,
                            )

                    elif line.lower().startswith("host "):
                        if state["current_host_block"]:
                            state["all_hosts_data"].append(
                                state["current_host_block"]
                            )

                        aliases = shlex.split(line[5:].strip(), comments=True)
                        state["current_host_block"] = {
                            "aliases": aliases,
                            "params": {},
                        }

                    elif state["current_host_block"] is not None:
                        parts = shlex.split(line, comments=True)
                        if len(parts) >= 2:
                            key = parts[0]
                            value = " ".join(parts[1:])
                            self._append_param(
                                state["current_host_block"]["params"],
                                key.lower(),
                                value,
                            )
        finally:
            active_files.remove(config_path)

    def _read_host_blocks(self, config_path, config_root=None):
        config_path = os.path.realpath(os.path.expanduser(config_path))
        if config_root is None:
            config_root = os.path.dirname(config_path)

        state = {
            "all_hosts_data": [],
            "current_host_block": None,
        }
        self._parse_config_file(config_path, state, set(), config_root)
        if state["current_host_block"]:
            state["all_hosts_data"].append(state["current_host_block"])

        # Separate wildcard rules from specific host rules
        specific_hosts = []
        wildcard_defaults = {}
        for block in state["all_hosts_data"]:
            is_wildcard = any(
                "*" in alias or "?" in alias for alias in block["aliases"]
            )
            if is_wildcard:
                # For simplicity, we only support a single `Host *` block for defaults.
                if block["aliases"] == ["*"]:
                    wildcard_defaults.update(block["params"])
            else:
                specific_hosts.append(block)

        return specific_hosts, wildcard_defaults

    def parse(self):
        config_path = os.path.expanduser("~/.ssh/config")
        if not os.path.exists(config_path):
            return []

        try:
            self._ssh_g_safe = True
            specific_hosts, wildcard_defaults = self._read_host_blocks(config_path)
        except (IOError, ValueError) as e:
            print(f"Warning: Could not read {config_path}: {e}", file=sys.stderr)
            return []

        final_hosts = []
        for host_block in specific_hosts:
            # Apply general defaults first, then host-specific params
            params = wildcard_defaults.copy()
            params.update(host_block["params"])

            # Create a separate entry for each alias
            for alias in host_block["aliases"]:
                final_hosts.append(
                    self._finalize_host_from_ssh(alias, params)
                    or self._finalize_host(alias, params)
                )

        return final_hosts

    def _ssh_g_config(self, alias):
        try:
            result = subprocess.run(
                ["ssh", "-G", alias],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None

        params = {}
        for line in result.stdout.splitlines():
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                key, value = parts
                self._append_param(params, key.lower(), value)
        return params

    def _finalize_host_from_ssh(self, alias, fallback_params=None):
        if not getattr(self, "_ssh_g_safe", True):
            return None
        params = self._ssh_g_config(alias)
        if not params:
            return None
        explicit_identity_files = self._param_values(
            fallback_params or {},
            "identityfile",
        )
        if explicit_identity_files:
            params = dict(params)
            params["identityfile"] = self._param_first(
                params,
                "identityfile",
                explicit_identity_files[0],
            )
        else:
            params = dict(params)
            params.pop("identityfile", None)
        return self._finalize_host(alias, params)

    def _finalize_host(self, alias, params):
        """Converts a parsed host entry into the format sshgo expects."""
        hostname = self._param_first(params, "hostname", alias)
        port = self._param_first(params, "port", "22")
        user = self._param_first(params, "user", "")
        id_file = self._param_first(params, "identityfile", "")
        if id_file:
            id_file = os.path.expanduser(id_file)  # Expand tilde

        host = {
            "type": "host",
            "name": f"{alias} (~/.ssh/config)",
            "host": hostname,
            "user": user,
            "id_file": id_file,
            "password": "",
            "mfa_secret": "",
            "source": "ssh_config",
        }
        if str(port) != "22":
            host["port"] = str(port)
        return host
