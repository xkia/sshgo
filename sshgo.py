#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import locale
import textwrap
import argparse
from host_manager import HostManager
from tui import Tui
from i18n import i18n


def handle_shortcut_commands(cmd_args, host_manager):
    host_alias = cmd_args[0]
    node = host_manager.find_host_by_alias(host_alias)
    if not node:
        print(f"Error: Host alias '{host_alias}' not found.", file=sys.stderr)
        sys.exit(1)

    if len(cmd_args) == 1:
        host_manager.execute_interactive_connection(node)
        return

    action = cmd_args[1]
    if action in ("upload", "download"):
        if len(cmd_args) != 4:
            print(
                f"Error: Incorrect number of arguments for {action}.", file=sys.stderr
            )
            print(
                f"Usage: {os.path.basename(sys.argv[0])} {host_alias} {action} <source_path> <destination_path>",
                file=sys.stderr,
            )
            sys.exit(1)

        path1, path2 = cmd_args[2], cmd_args[3]
        host_manager.execute_sftp_transfer(node, action, path1, path2)

    else:
        remote_command = " ".join(cmd_args[1:])
        host_manager.execute_interactive_connection(node, remote_command)


def run_tui(host_manager):
    script_dir = os.path.dirname(os.path.realpath(__file__))
    if not host_manager.get_hosts():
        print("Welcome to sshgo! Your host list is empty.")
        try:
            choice = (
                input("Would you like to add your first host? [Y/n]: ").strip().lower()
            )
            if choice != "n":
                try:
                    tui = Tui(host_manager, mode="add")
                    tui.run_add_flow()
                finally:
                    tui.restore_screen()
            else:
                print(
                    "Exiting. You can add a host later by running sshgo and pressing 'a'."
                )
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
        sys.exit(0)

    for script in ["login.exp", "sftp_login.exp", "relay_transfer.exp"]:
        script_path = os.path.join(script_dir, script)
        try:
            os.chmod(script_path, 0o755)
        except FileNotFoundError:
            pass

    try:
        tui = Tui(host_manager)
        tui.run()
    finally:
        tui.restore_screen()

    if tui.exit_reason == "connected":
        sys.exit(128)


def _probe_config_files(base_dir):
    """Return the default JSONC config path for a directory."""
    return os.path.join(base_dir, "hosts.json")


def _default_config_path(script_dir):
    user_config = _probe_config_files(os.path.expanduser("~/.config/sshgo"))
    if os.path.exists(user_config):
        return user_config
    return _probe_config_files(script_dir)


def show_history(host_manager, limit, filter_name):
    records = host_manager.audit.get_history(limit=limit, filter_name=filter_name)
    if not records:
        print("No connection history found.")
        return
    print(f"{'Time':<22} {'Name':<20} {'Host':<25} {'User':<10} {'Auth':<10} {'Result'}")
    print("-" * 110)
    for r in records:
        host = r.get("endpoint") or r.get("host", "")
        if r.get("port") and ":" not in host:
            host = f"{host}:{r.get('port')}"
        print(
            f"{r.get('ts', ''):<22} {r.get('name', ''):<20} {host:<25} "
            f"{r.get('user', ''):<10} {r.get('auth', ''):<10} {r.get('result', '')}"
        )


def main():
    locale.setlocale(locale.LC_ALL, "")

    parser = argparse.ArgumentParser(
        description="A TUI-based SSH connection manager with command-line shortcuts.",
        epilog=textwrap.dedent(
            """
        Shortcut Commands:
          alias              Quickly connect to the host specified by 'alias'.
          alias command...   Execute a remote command on the host.
          alias upload ...   Upload a file. Usage: %(prog)s alias upload <local_path> <remote_path>
          alias download ..  Download a file. Usage: %(prog)s alias download <remote_path> <local_path>
        """
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--toggle-encryption",
        action="store_true",
        help="Enable or disable password encryption",
    )
    parser.add_argument(
        "--toggle-ssh-config",
        action="store_true",
        help="Enable or disable importing hosts from ~/.ssh/config",
    )
    parser.add_argument(
        "--toggle-language",
        action="store_true",
        help="Toggle language between English and Chinese",
    )
    parser.add_argument(
        "--toggle-details",
        action="store_true",
        help="Toggle the host detail preview pane in the TUI",
    )
    parser.add_argument(
        "--toggle-ssh-agent",
        action="store_true",
        help="Enable or disable SSH agent for this session",
    )
    parser.add_argument(
        "--audit-full",
        action="store_true",
        help="Enable full audit logging for this session",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="Show recent connection history",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of history records to show (default: 10)",
    )
    parser.add_argument(
        "--filter",
        dest="filter_name",
        help="Filter history by host name",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate the configuration file",
    )
    parser.add_argument(
        "--edit",
        action="store_true",
        help="Edit configuration in TUI mode",
    )
    parser.add_argument(
        "-e",
        "--extra-config",
        help="Use a different configuration file or directory for this session only",
    )
    parser.add_argument("cmd_args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    args = parser.parse_args()

    config_path = None

    if args.extra_config:
        config_path = os.path.abspath(os.path.expanduser(args.extra_config))

    if not config_path:
        config_path_from_env = os.getenv("SSHGO_CONFIG_PATH")
        if config_path_from_env:
            config_path = os.path.abspath(os.path.expanduser(config_path_from_env))

    if config_path and os.path.isdir(config_path):
        config_path = _probe_config_files(config_path)

    if not config_path:
        script_dir = os.path.dirname(os.path.realpath(__file__))
        config_path = _default_config_path(script_dir)

    data_dir = os.getenv("SSHGO_DATA_DIR")
    host_manager = HostManager(
        config_path,
        data_dir=data_dir,
        auto_migrate=not args.validate,
    )

    lang = host_manager.config.get("language", "en")
    i18n.set_language(lang)

    if args.audit_full:
        host_manager._audit_full = True

    if args.validate:
        errors = host_manager.validate_config()
        if errors:
            print(i18n.get("validate_failed") + "：")
            for err in errors:
                print(f"  - {err}")
            sys.exit(1)
        else:
            print(i18n.get("validate_ok"))
        return

    if args.edit:
        tui = Tui(host_manager, mode="edit")
        tui.run()
        return

    if args.history:
        show_history(host_manager, limit=args.limit, filter_name=args.filter_name)
        return

    if args.cmd_args:
        handle_shortcut_commands(args.cmd_args, host_manager)
        return

    elif args.toggle_encryption:
        host_manager.toggle_encryption()
    elif args.toggle_ssh_config:
        host_manager.toggle_ssh_config()
    elif args.toggle_language:
        host_manager.toggle_language()
    elif args.toggle_details:
        host_manager.toggle_detail_pane()
    elif args.toggle_ssh_agent:
        host_manager.toggle_ssh_agent()

    else:
        run_tui(host_manager)


if __name__ == "__main__":
    main()
