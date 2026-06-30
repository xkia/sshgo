#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys


class SshConfigParser:

    def parse(self):
        config_path = os.path.expanduser("~/.ssh/config")
        if not os.path.exists(config_path):
            return []

        all_hosts_data = []
        wildcard_defaults = {}
        current_host_block = None

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    if line.lower().startswith("host "):
                        if current_host_block:
                            all_hosts_data.append(current_host_block)

                        aliases = line[5:].strip().split()
                        current_host_block = {"aliases": aliases, "params": {}}

                    elif current_host_block is not None:
                        parts = line.split(maxsplit=1)
                        if len(parts) == 2:
                            key, value = parts
                            current_host_block["params"][key.lower()] = value

            if current_host_block:
                all_hosts_data.append(current_host_block)

        except IOError as e:
            print(f"Warning: Could not read {config_path}: {e}", file=sys.stderr)
            return []

        # Separate wildcard rules from specific host rules
        specific_hosts = []
        for block in all_hosts_data:
            is_wildcard = any(
                "*" in alias or "?" in alias for alias in block["aliases"]
            )
            if is_wildcard:
                # For simplicity, we only support a single `Host *` block for defaults.
                if block["aliases"] == ["*"]:
                    wildcard_defaults.update(block["params"])
            else:
                specific_hosts.append(block)

        # Finalize hosts by applying defaults
        final_hosts = []
        for host_block in specific_hosts:
            # Apply general defaults first, then host-specific params
            params = wildcard_defaults.copy()
            params.update(host_block["params"])

            # Create a separate entry for each alias
            for alias in host_block["aliases"]:
                final_hosts.append(self._finalize_host(alias, params))

        return final_hosts

    def _finalize_host(self, alias, params):
        """Converts a parsed host entry into the format sshgo expects."""
        hostname = params.get("hostname", alias)
        port = params.get("port", "22")
        user = params.get("user", "")
        id_file = params.get("identityfile", "")
        if id_file:
            id_file = os.path.expanduser(id_file)  # Expand tilde

        return {
            "type": "host",
            "name": f"{alias} (~/.ssh/config)",
            "host": f"{hostname}:{port}",
            "user": user,
            "id_file": id_file,
            "password": "",
            "mfa_secret": "",
            "source": "ssh_config",
        }
