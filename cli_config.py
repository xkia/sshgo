#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys

from config_store import ConfigStore
from config_validation import merge_config, validate_hosts_config
from host_manager import HostManager
from i18n import i18n


def _probe_config_files(base_dir):
    """Return the default JSONC config path for a directory."""
    return os.path.join(base_dir, "hosts.json")


def _default_config_path(script_dir):
    user_config = _probe_config_files(os.path.expanduser("~/.config/sshgo"))
    if os.path.exists(user_config):
        return user_config
    return _probe_config_files(script_dir)


def load_config_snapshot(
    config_path,
    validator=validate_hosts_config,
    allow_missing=False,
):
    try:
        data = ConfigStore(config_path).read()
    except FileNotFoundError:
        if not allow_missing:
            return None, [i18n.get("validate_config_not_found", path=config_path)]
        data = {"config": {}, "hosts": []}
    except Exception as e:
        return None, [f"{i18n.get('validate_config_invalid')}: {e}"]

    raw_config = (
        data.get("config", {})
        if isinstance(data, dict) and isinstance(data.get("config", {}), dict)
        else {}
    )
    language = raw_config.get("language")
    if isinstance(language, str):
        i18n.set_language(language)
    return data, validator(data)


def effective_config_from_snapshot(snapshot):
    raw_config = (
        snapshot.get("config", {})
        if isinstance(snapshot, dict)
        and isinstance(snapshot.get("config", {}), dict)
        else {}
    )
    return merge_config(raw_config)


def runtime_data_dir_from_snapshot(snapshot, override=None):
    if override:
        return os.path.expanduser(override)
    configured = effective_config_from_snapshot(snapshot).get("data_dir")
    if isinstance(configured, str) and configured.strip():
        return os.path.expanduser(configured)
    return os.path.expanduser("~/.sshgo")


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
    return True
