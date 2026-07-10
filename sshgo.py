#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import locale
import textwrap
import argparse
import shlex
import cli_config
import cli_diagnostics
from audit_logger import AuditLogger
from config_validation import validate_hosts_config_for_load
from endpoint import DEFAULT_PORT, format_endpoint
from host_manager import HostManager
from tui import Tui
import tui_flows
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
    if not host_manager.get_hosts():
        print(i18n.get("first_run_welcome"))
        try:
            choice = input(i18n.get("first_run_add_prompt")).strip().lower()
            if choice != "n":
                tui = None
                try:
                    tui = Tui(host_manager, mode="add")
                    tui_flows.run_add_flow(tui)
                finally:
                    if tui is not None:
                        tui.restore_screen()
            else:
                print(i18n.get("first_run_exit_hint"))
        except (KeyboardInterrupt, EOFError):
            print("\n" + i18n.get("operation_cancelled"))
        sys.exit(0)

    tui = None
    try:
        tui = Tui(host_manager)
        tui.run()
    finally:
        if tui is not None:
            tui.restore_screen()

    if tui is not None and tui.exit_reason == "connected":
        sys.exit(128)


def show_history(audit_logger, limit, filter_name):
    records = audit_logger.get_history(limit=limit, filter_name=filter_name)
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


def _positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def _print_validation_result(errors):
    if errors:
        print(i18n.get("validate_failed") + "：")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(i18n.get("validate_ok"))
    return 0


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
        type=_positive_int,
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
        config_path = cli_config._probe_config_files(config_path)

    if not config_path:
        script_dir = os.path.dirname(os.path.realpath(__file__))
        config_path = cli_config._default_config_path(script_dir)

    if args.list_backups:
        sys.exit(cli_config.show_config_backups(config_path))

    if args.restore_backup is not None:
        sys.exit(cli_config.restore_config_backup(config_path, args.restore_backup))

    data_dir = os.getenv("SSHGO_DATA_DIR")

    if args.validate:
        _, errors = cli_config.load_config_snapshot(config_path)
        code = _print_validation_result(errors)
        if code:
            sys.exit(code)
        return

    if args.history:
        snapshot, errors = cli_config.load_config_snapshot(
            config_path,
            validator=validate_hosts_config_for_load,
            allow_missing=True,
        )
        if errors:
            sys.exit(_print_validation_result(errors))
        audit = AuditLogger(
            cli_config.runtime_data_dir_from_snapshot(snapshot, override=data_dir)
        )
        show_history(audit, limit=args.limit, filter_name=args.filter_name)
        return

    if args.doctor:
        sys.exit(cli_diagnostics.run_doctor_for_path(config_path, data_dir=data_dir))

    host_manager = HostManager(
        config_path,
        data_dir=data_dir,
        auto_migrate=False,
    )

    lang = host_manager.config.get("language", "en")
    i18n.set_language(lang)

    if args.audit_full:
        host_manager.enable_full_audit()

    if cli_config._should_persist_node_id_migration(args):
        host_manager.persist_node_id_migration_if_needed()

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

    else:
        run_tui(host_manager)


if __name__ == "__main__":
    main()
