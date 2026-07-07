#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import locale
import textwrap
import argparse
import shlex
import shutil
from endpoint import DEFAULT_PORT, format_endpoint
from cli_config import (
    _default_config_path,
    _probe_config_files,
    _should_persist_node_id_migration,
    restore_config_backup as _restore_config_backup,
    show_config_backups as _show_config_backups,
)
from cli_diagnostics import (
    run_doctor as _run_doctor,
    run_doctor_for_path as _run_doctor_for_path,
)
from host_manager import HostManager
from tui import Tui
from i18n import i18n


def _format_alias_matches(matches):
    return ", ".join(sorted(node.get("name", "") for node in matches))


def _resolve_shortcut_alias(host_alias, host_manager):
    result = host_manager.resolve_host_alias(host_alias)
    if result["status"] == "found":
        return result["node"]
    if result["status"] == "ambiguous":
        print(
            i18n.get(
                "alias_ambiguous",
                alias=host_alias,
                candidates=_format_alias_matches(result["matches"]),
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    print(i18n.get("alias_not_found", alias=host_alias), file=sys.stderr)
    sys.exit(1)


def handle_shortcut_commands(cmd_args, host_manager, print_command=False):
    host_alias = cmd_args[0]
    node = _resolve_shortcut_alias(host_alias, host_manager)

    try:
        if len(cmd_args) == 1:
            if print_command:
                print(shlex.join(host_manager.build_interactive_launch_command_args(node)))
                return
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
            if print_command:
                print(
                    shlex.join(
                        host_manager.build_file_transfer_launch_command_args(
                            node, action, path1, path2
                        )
                    )
                )
                return
            host_manager.execute_file_transfer(node, action, path1, path2)

        else:
            remote_command = shlex.join(cmd_args[1:])
            if print_command:
                print(
                    shlex.join(
                        host_manager.build_interactive_launch_command_args(
                            node, remote_command
                        )
                    )
                )
                return
            host_manager.execute_interactive_connection(node, remote_command)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def handle_interactive_sftp_command(host_alias, host_manager, print_command=False):
    node = _resolve_shortcut_alias(host_alias, host_manager)
    try:
        if print_command:
            print(
                shlex.join(host_manager.build_interactive_sftp_launch_command_args(node))
            )
            return
        host_manager.execute_interactive_sftp_session(node)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def run_tui(host_manager):
    script_dir = os.path.dirname(os.path.realpath(__file__))
    if not host_manager.get_hosts():
        print("Welcome to sshgo! Your host list is empty.")
        try:
            choice = (
                input("Would you like to add your first host? [Y/n]: ").strip().lower()
            )
            if choice != "n":
                tui = None
                try:
                    tui = Tui(host_manager, mode="add")
                    tui.run_add_flow()
                finally:
                    if tui is not None:
                        tui.restore_screen()
            else:
                print(
                    "Exiting. You can add a host later by running sshgo and pressing 'a'."
                )
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
        sys.exit(0)

    for script in [
        "login.exp",
        "sftp_login.exp",
        "relay_transfer.exp",
        "sftp_ssh_wrapper.py",
    ]:
        script_path = os.path.join(script_dir, script)
        try:
            os.chmod(script_path, 0o755)
        except FileNotFoundError:
            pass

    tui = None
    try:
        tui = Tui(host_manager)
        tui.run()
    finally:
        if tui is not None:
            tui.restore_screen()

    if tui is not None and tui.exit_reason == "connected":
        sys.exit(128)


def run_edit_tui(host_manager):
    tui = None
    try:
        tui = Tui(host_manager, mode="edit")
        tui.run()
    finally:
        if tui is not None:
            tui.restore_screen()


def show_history(host_manager, limit, filter_name):
    records = host_manager.audit.get_history(limit=limit, filter_name=filter_name)
    if not records:
        print("No connection history found.")
        return
    print(f"{'Time':<22} {'Name':<20} {'Host':<25} {'User':<10} {'Auth':<10} {'Result'}")
    print("-" * 110)
    for r in records:
        host = r.get("endpoint") or r.get("host", "")
        if r.get("host") and r.get("port") and not r.get("endpoint"):
            host = format_endpoint(
                r.get("host"),
                r.get("port"),
                default_port=DEFAULT_PORT,
                include_default=True,
            )
        print(
            f"{r.get('ts', ''):<22} {r.get('name', ''):<20} {host:<25} "
            f"{r.get('user', ''):<10} {r.get('auth', ''):<10} {r.get('result', '')}"
        )


def show_config_backups(config_path):
    return _show_config_backups(config_path, host_manager_cls=HostManager)


def restore_config_backup(config_path, index):
    return _restore_config_backup(
        config_path,
        index,
        host_manager_cls=HostManager,
    )


def run_doctor_for_path(config_path, data_dir=None):
    return _run_doctor_for_path(
        config_path,
        data_dir=data_dir,
        host_manager_cls=HostManager,
        tui_cls=Tui,
        which=shutil.which,
    )


def run_doctor(host_manager, config_path, config_errors=None,
               config_snapshot=None, data_dir=None):
    return _run_doctor(
        host_manager,
        config_path,
        config_errors=config_errors,
        config_snapshot=config_snapshot,
        data_dir=data_dir,
        tui_cls=Tui,
        which=shutil.which,
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
          --sftp alias       Open an interactive SFTP session for the host.
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
        help="Enable full audit logging; command/path context may include sensitive arguments",
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
        "--print-command",
        action="store_true",
        help="Print the resolved command for a shortcut without connecting",
    )
    parser.add_argument(
        "--sftp",
        metavar="ALIAS",
        help="Open an interactive SFTP session for a host alias",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Run local diagnostics for config, dependencies, scripts, and runtime data",
    )
    parser.add_argument(
        "--list-backups",
        action="store_true",
        help="List rotated config backups for the resolved config path",
    )
    parser.add_argument(
        "--restore-backup",
        metavar="INDEX",
        help="Restore a rotated config backup by index: 0=.bak, 1=.bak.1",
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

    if args.list_backups:
        sys.exit(show_config_backups(config_path))

    if args.restore_backup is not None:
        sys.exit(restore_config_backup(config_path, args.restore_backup))

    data_dir = os.getenv("SSHGO_DATA_DIR")

    if args.doctor:
        sys.exit(run_doctor_for_path(config_path, data_dir=data_dir))

    host_manager = HostManager(
        config_path,
        data_dir=data_dir,
        auto_migrate=False,
    )

    lang = host_manager.config.get("language", "en")
    i18n.set_language(lang)

    if args.audit_full:
        host_manager.enable_full_audit()

    if _should_persist_node_id_migration(args):
        host_manager.persist_node_id_migration_if_needed()

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
        run_edit_tui(host_manager)
        return

    if args.history:
        show_history(host_manager, limit=args.limit, filter_name=args.filter_name)
        return

    if args.sftp:
        if args.cmd_args:
            parser.error("--sftp does not accept extra arguments")
        handle_interactive_sftp_command(
            args.sftp,
            host_manager,
            print_command=args.print_command,
        )
        return

    if args.cmd_args:
        handle_shortcut_commands(
            args.cmd_args,
            host_manager,
            print_command=args.print_command,
        )
        return

    if args.print_command:
        parser.error("--print-command requires a shortcut command or --sftp")

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
