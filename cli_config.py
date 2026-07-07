#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys

from host_manager import HostManager


def _probe_config_files(base_dir):
    """Return the default JSONC config path for a directory."""
    return os.path.join(base_dir, "hosts.json")


def _default_config_path(script_dir):
    user_config = _probe_config_files(os.path.expanduser("~/.config/sshgo"))
    if os.path.exists(user_config):
        return user_config
    return _probe_config_files(script_dir)


def show_config_backups(config_path, host_manager_cls=HostManager):
    backups = host_manager_cls.list_config_backups(config_path)
    if not backups:
        print(f"No config backups found for {config_path}.")
        return 1

    print(f"Config backups for {config_path}:")
    for backup in backups:
        print(
            "[{index}] {path} ({size} bytes, {mtime})".format(
                index=backup["index"],
                path=backup["path"],
                size=backup["size"],
                mtime=backup["mtime"],
            )
        )
    return 0


def restore_config_backup(config_path, index, host_manager_cls=HostManager):
    try:
        result = host_manager_cls.restore_config_backup(config_path, index)
    except FileNotFoundError as e:
        print(f"Error: Backup not found: {e.filename or e}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(
        "Restored backup [{index}] {source} -> {target}".format(
            index=result["index"],
            source=result["source"],
            target=result["target"],
        )
    )
    return 0


def _should_persist_node_id_migration(args):
    if args.validate or args.doctor or args.history or args.print_command:
        return False
    if args.toggle_encryption:
        return False
    return True
