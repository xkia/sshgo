import json
import os
import builtins
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import cli_config
import cli_diagnostics
import host_manager as host_manager_module
import sshgo as sshgo_module
from host_manager import HostManager

try:
    from fixtures import jump_with_target, manager_for_config
except ImportError:
    from tests.fixtures import jump_with_target, manager_for_config


class CliTests(unittest.TestCase):
    def _manager(self, temp_dir):
        return manager_for_config(temp_dir, hosts=[jump_with_target()])

    def _doctor_tui_cls(self, alternate_screen=True):
        class FakeTui:
            @staticmethod
            def terminal_supports_alternate_screen():
                return alternate_screen

        return FakeTui

    def _which_all(self, prefix="/usr/bin"):
        return lambda name: f"{prefix}/{name}"

    def _write_legacy_config(self, temp_dir):
        path = os.path.join(temp_dir, "hosts.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "config": {"import_ssh_config": False},
                    "hosts": [
                        {
                            "type": "host",
                            "name": "legacy",
                            "host": "legacy.example.com",
                            "user": "deploy",
                            "password": "pw",
                        }
                    ],
                },
                f,
            )
        return path

    def _run_main_with_args(self, argv, data_dir):
        old_argv = sys.argv
        old_data_dir = os.environ.get("SSHGO_DATA_DIR")
        sys.argv = ["sshgo.py"] + argv
        os.environ["SSHGO_DATA_DIR"] = data_dir
        try:
            return sshgo_module.main()
        finally:
            sys.argv = old_argv
            if old_data_dir is None:
                os.environ.pop("SSHGO_DATA_DIR", None)
            else:
                os.environ["SSHGO_DATA_DIR"] = old_data_dir

    def _saved_host(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)["hosts"][0]

    def test_alias_resolution_rejects_ambiguous_prefixes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "config": {"import_ssh_config": False},
                "hosts": [
                    {
                        "type": "host",
                        "name": "prod-db",
                        "host": "db.example.com",
                        "user": "deploy",
                        "password": "pw",
                    },
                    {
                        "type": "host",
                        "name": "prod-web",
                        "host": "web.example.com",
                        "user": "deploy",
                        "password": "pw",
                    },
                ],
            }
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)
            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))

            result = manager.resolve_host_alias("prod")
            self.assertEqual(result["status"], "ambiguous")

            stderr = StringIO()
            with redirect_stderr(stderr):
                with self.assertRaises(SystemExit):
                    sshgo_module.handle_shortcut_commands(["prod"], manager)

            message = stderr.getvalue()
            self.assertIn("ambiguous", message)
            self.assertIn("prod-db", message)
            self.assertIn("prod-web", message)

    def test_print_command_does_not_persist_node_id_migration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_legacy_config(temp_dir)

            with redirect_stdout(StringIO()):
                self._run_main_with_args(
                    ["-e", path, "--print-command", "legacy"],
                    os.path.join(temp_dir, "data"),
                )

            self.assertNotIn("id", self._saved_host(path))
            self.assertFalse(os.path.exists(path + ".bak"))

    def test_history_does_not_persist_node_id_migration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_legacy_config(temp_dir)

            with redirect_stdout(StringIO()):
                self._run_main_with_args(
                    ["-e", path, "--history"],
                    os.path.join(temp_dir, "data"),
                )

            self.assertNotIn("id", self._saved_host(path))
            self.assertFalse(os.path.exists(path + ".bak"))

    def test_validate_does_not_persist_node_id_migration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_legacy_config(temp_dir)

            with redirect_stdout(StringIO()):
                self._run_main_with_args(
                    ["-e", path, "--validate"],
                    os.path.join(temp_dir, "data"),
                )

            self.assertNotIn("id", self._saved_host(path))
            self.assertFalse(os.path.exists(path + ".bak"))

    def test_doctor_does_not_persist_node_id_migration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_legacy_config(temp_dir)
            real_run_doctor_for_path = cli_diagnostics.run_doctor_for_path
            cli_diagnostics.run_doctor_for_path = lambda *args, **kwargs: 0
            try:
                with redirect_stdout(StringIO()):
                    with self.assertRaises(SystemExit) as cm:
                        self._run_main_with_args(
                            ["-e", path, "--doctor"],
                            os.path.join(temp_dir, "data"),
                        )
                    self.assertEqual(cm.exception.code, 0)
            finally:
                cli_diagnostics.run_doctor_for_path = real_run_doctor_for_path

            self.assertNotIn("id", self._saved_host(path))
            self.assertFalse(os.path.exists(path + ".bak"))

    def test_shortcut_execution_persists_node_id_migration_before_handoff(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_legacy_config(temp_dir)
            calls = []
            real_execute = host_manager_module.HostManager.execute_interactive_connection

            def fake_execute(self, node):
                calls.append(node.get("name"))

            host_manager_module.HostManager.execute_interactive_connection = fake_execute
            try:
                self._run_main_with_args(
                    ["-e", path, "legacy"],
                    os.path.join(temp_dir, "data"),
                )
            finally:
                host_manager_module.HostManager.execute_interactive_connection = real_execute

            self.assertEqual(calls, ["legacy"])
            self.assertIn("id", self._saved_host(path))
            self.assertTrue(os.path.exists(path + ".bak"))

    def test_interactive_sftp_execution_persists_node_id_migration_before_handoff(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_legacy_config(temp_dir)
            calls = []
            real_execute = (
                host_manager_module.HostManager.execute_interactive_sftp_session
            )

            def fake_execute(self, node):
                calls.append(node.get("name"))

            host_manager_module.HostManager.execute_interactive_sftp_session = (
                fake_execute
            )
            try:
                self._run_main_with_args(
                    ["-e", path, "--sftp", "legacy"],
                    os.path.join(temp_dir, "data"),
                )
            finally:
                host_manager_module.HostManager.execute_interactive_sftp_session = (
                    real_execute
                )

            self.assertEqual(calls, ["legacy"])
            self.assertIn("id", self._saved_host(path))
            self.assertTrue(os.path.exists(path + ".bak"))

    def test_alias_resolution_keeps_unique_prefix_convenience(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            result = manager.resolve_host_alias("tar")
            self.assertEqual(result["status"], "found")
            self.assertEqual(result["node"]["name"], "target")

    def test_print_command_outputs_resolved_handoff_without_secrets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)

            stdout = StringIO()
            with redirect_stdout(stdout):
                sshgo_module.handle_shortcut_commands(
                    ["target"],
                    manager,
                    print_command=True,
                )

            rendered = stdout.getvalue()
            self.assertIn("login.exp", rendered)
            self.assertIn("-h target.internal", rendered)
            self.assertIn("-J jumpuser@jump.example.com:2200", rendered)
            self.assertNotIn("target-pass", rendered)
            self.assertNotIn("jump-pass", rendered)
            self.assertNotIn("JBSWY3DPEHPK3PXP", rendered)

    def test_print_command_outputs_transfer_handoff_without_secrets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)

            stdout = StringIO()
            with redirect_stdout(stdout):
                sshgo_module.handle_shortcut_commands(
                    ["target", "upload", "local file.txt", "/tmp/remote file.txt"],
                    manager,
                    print_command=True,
                )

            rendered = stdout.getvalue()
            self.assertIn("sftp_login.exp", rendered)
            self.assertIn("-action upload", rendered)
            self.assertIn("'local file.txt'", rendered)
            self.assertNotIn("target-pass", rendered)
            self.assertNotIn("jump-pass", rendered)

    def test_print_command_outputs_interactive_sftp_handoff_without_secrets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)

            stdout = StringIO()
            with redirect_stdout(stdout):
                self._run_main_with_args(
                    [
                        "-e",
                        manager.json_path,
                        "--print-command",
                        "--sftp",
                        "target",
                    ],
                    os.path.join(temp_dir, "data"),
                )

            rendered = stdout.getvalue()
            self.assertIn("sftp_login.exp", rendered)
            self.assertIn("-action interactive", rendered)
            self.assertIn("-tunnel-proxy-command", rendered)
            self.assertNotIn("-local", rendered)
            self.assertNotIn("-remote", rendered)
            self.assertNotIn("<sshgo-generated-batch-file>", rendered)
            self.assertNotIn("sftp_ssh_wrapper.py", rendered)
            self.assertNotIn("target-pass", rendered)
            self.assertNotIn("jump-pass", rendered)

    def test_shell_wrapper_preserves_invocation_cwd_for_sftp_transfer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, "hosts.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "config": {"import_ssh_config": False},
                        "hosts": [
                            {
                                "type": "host",
                                "name": "target",
                                "host": "target.example.com",
                                "user": "deploy",
                            }
                        ],
                    },
                    f,
                )

            fake_sftp = os.path.join(temp_dir, "sftp")
            cwd_path = os.path.join(temp_dir, "sftp.cwd")
            with open(fake_sftp, "w", encoding="utf-8") as f:
                f.write(
                    """#!/bin/sh
pwd > "$SSHGO_FAKE_SFTP_CWD"
exit 0
"""
                )
            os.chmod(fake_sftp, 0o755)

            repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            env = os.environ.copy()
            env["PATH"] = temp_dir + os.pathsep + env.get("PATH", "")
            env["SSHGO_DATA_DIR"] = os.path.join(temp_dir, "data")
            env["SSHGO_FAKE_SFTP_CWD"] = cwd_path
            result = subprocess.run(
                [
                    os.path.join(repo_dir, "sshgo.sh"),
                    "-e",
                    config_path,
                    "target",
                    "upload",
                    "./local.txt",
                    "/tmp/remote.txt",
                ],
                cwd=temp_dir,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with open(cwd_path, "r", encoding="utf-8") as f:
                self.assertEqual(
                    os.path.realpath(f.read().strip()),
                    os.path.realpath(temp_dir),
                )

    def test_interactive_sftp_rejects_extra_positional_arguments(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)

            stderr = StringIO()
            with redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as cm:
                    self._run_main_with_args(
                        ["-e", manager.json_path, "--sftp", "target", "extra"],
                        os.path.join(temp_dir, "data"),
                    )

            self.assertEqual(cm.exception.code, 2)
            self.assertIn("--sftp does not accept extra arguments", stderr.getvalue())

    def test_sftp_positional_shortcut_remains_remote_command(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)

            stdout = StringIO()
            with redirect_stdout(stdout):
                sshgo_module.handle_shortcut_commands(
                    ["target", "sftp"],
                    manager,
                    print_command=True,
                )

            rendered = stdout.getvalue()
            self.assertIn("login.exp", rendered)
            self.assertIn("-c sftp", rendered)
            self.assertNotIn("sftp_login.exp", rendered)

    def test_remote_command_shortcut_uses_shell_safe_joining(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            captured = {}
            real_execve = host_manager_module.os.execve

            def fake_execve(path, args, env):
                captured["args"] = args
                raise OSError(5, "fake")

            host_manager_module.os.execve = fake_execve
            try:
                with redirect_stderr(StringIO()):
                    with self.assertRaises(SystemExit):
                        sshgo_module.handle_shortcut_commands(
                            ["target", "echo", "a b", ";", "whoami"],
                            manager,
                        )
            finally:
                host_manager_module.os.execve = real_execve

            args = captured["args"]
            self.assertEqual(
                args[args.index("-c") + 1],
                "echo 'a b' ';' whoami",
            )

    def test_default_config_prefers_user_config_when_present(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home_dir = os.path.join(temp_dir, "home")
            script_dir = os.path.join(temp_dir, "script")
            user_config_dir = os.path.join(home_dir, ".config", "sshgo")
            os.makedirs(user_config_dir)
            os.makedirs(script_dir)
            user_config = os.path.join(user_config_dir, "hosts.json")
            with open(user_config, "w", encoding="utf-8") as f:
                json.dump({"config": {}, "hosts": []}, f)

            old_home = os.environ.get("HOME")
            os.environ["HOME"] = home_dir
            try:
                self.assertEqual(
                    cli_config._default_config_path(script_dir),
                    user_config,
                )
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def test_default_config_falls_back_to_script_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home_dir = os.path.join(temp_dir, "home")
            script_dir = os.path.join(temp_dir, "script")
            os.makedirs(os.path.join(home_dir, ".config", "sshgo"))
            os.makedirs(script_dir)

            old_home = os.environ.get("HOME")
            os.environ["HOME"] = home_dir
            try:
                self.assertEqual(
                    cli_config._default_config_path(script_dir),
                    os.path.join(script_dir, "hosts.json"),
                )
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def test_doctor_reports_local_preflight_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = cli_diagnostics.run_doctor(
                    manager,
                    manager.json_path,
                    tui_cls=self._doctor_tui_cls(True),
                    which=lambda name: "/usr/bin/expect",
                )

            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("[PASS] Config validation", output)
            self.assertIn("[PASS] Alternate screen", output)
            self.assertIn("[PASS] TUI screen policy", output)
            self.assertIn("[PASS] expect", output)
            self.assertIn("[PASS] ssh", output)
            self.assertIn("[PASS] sftp", output)
            self.assertIn("[PASS] scp", output)
            self.assertIn("sftp_ssh_wrapper.py", output)
            self.assertIn("Runtime data dir", output)

    def test_doctor_accepts_explicit_dependency_bindings(self):
        class FakeShutil:
            @staticmethod
            def which(name):
                return f"/fake/{name}"

        class FakeTui:
            @staticmethod
            def terminal_supports_alternate_screen():
                return False

        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = cli_diagnostics.run_doctor(
                    manager,
                    manager.json_path,
                    tui_cls=FakeTui,
                    which=FakeShutil.which,
                )

            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("[PASS] expect: /fake/expect", output)
            self.assertIn("[WARN] Alternate screen", output)

    def test_doctor_warns_when_alternate_screen_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = cli_diagnostics.run_doctor(
                    manager,
                    manager.json_path,
                    tui_cls=self._doctor_tui_cls(False),
                    which=self._which_all(),
                )

            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("[WARN] Alternate screen", output)
            self.assertIn("TUI output may remain in terminal history", output)

    def test_doctor_warns_for_invalid_tui_screen_policy_without_crashing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            manager.config["tui_screen_policy"] = []
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = cli_diagnostics.run_doctor(
                    manager,
                    manager.json_path,
                    tui_cls=self._doctor_tui_cls(True),
                    which=self._which_all(),
                )

            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("[WARN] TUI screen policy", output)
            self.assertIn("invalid value: []", output)

    def test_doctor_for_path_handles_parseable_invalid_tui_screen_policy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"config": {"tui_screen_policy": []}, "hosts": []}, f)

            stdout = StringIO()
            with redirect_stdout(stdout):
                code = cli_diagnostics.run_doctor_for_path(
                    path,
                    data_dir=os.path.join(temp_dir, "data"),
                    tui_cls=self._doctor_tui_cls(True),
                    which=self._which_all(),
                )

            self.assertEqual(code, 1)
            output = stdout.getvalue()
            self.assertIn("[FAIL] Config validation", output)
            self.assertIn("config.tui_screen_policy must be a string", output)
            self.assertIn("[WARN] TUI screen policy", output)
            self.assertIn("invalid value: []", output)

    def test_doctor_fails_when_openssh_transfer_tool_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)

            def fake_which(name):
                if name == "sftp":
                    return None
                return f"/usr/bin/{name}"

            stdout = StringIO()
            with redirect_stdout(stdout):
                code = cli_diagnostics.run_doctor(
                    manager,
                    manager.json_path,
                    tui_cls=self._doctor_tui_cls(True),
                    which=fake_which,
                )

            self.assertEqual(code, 1)
            output = stdout.getvalue()
            self.assertIn("[FAIL] sftp", output)
            self.assertIn("[PASS] ssh", output)
            self.assertIn("[PASS] scp", output)

    def test_doctor_reports_malformed_config_without_host_manager_load(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("{bad json")

            stdout = StringIO()
            with redirect_stdout(stdout):
                code = cli_diagnostics.run_doctor_for_path(
                    path,
                    data_dir=os.path.join(temp_dir, "data"),
                    host_manager_cls=lambda *args, **kwargs: self.fail(
                        "malformed config should not construct HostManager"
                    ),
                    tui_cls=self._doctor_tui_cls(True),
                    which=lambda name: "/usr/bin/expect",
                )

            output = stdout.getvalue()
            self.assertEqual(code, 1)
            self.assertIn("[PASS] Config path", output)
            self.assertIn("[FAIL] Config validation", output)
            self.assertIn("[PASS] expect", output)
            self.assertIn("Runtime data dir", output)

    def test_doctor_for_encrypted_config_skips_host_manager_decryption(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "config": {
                            "import_ssh_config": False,
                            "encryption_enabled": True,
                            "encryption_salt": "MTIzNDU2Nzg5MDEyMzQ1Ng==",
                        },
                        "hosts": [
                            {
                                "type": "host",
                                "name": "encrypted",
                                "host": "example.com",
                                "user": "deploy",
                                "password": "ciphertext",
                            }
                        ],
                    },
                    f,
                )

            stdout = StringIO()
            with redirect_stdout(stdout):
                code = cli_diagnostics.run_doctor_for_path(
                    path,
                    data_dir=os.path.join(temp_dir, "data"),
                    host_manager_cls=lambda *args, **kwargs: self.fail(
                        "encrypted doctor should not construct HostManager"
                    ),
                    tui_cls=self._doctor_tui_cls(True),
                    which=self._which_all(),
                )

            output = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("[PASS] Config validation", output)
            self.assertIn("[PASS] Runtime data dir", output)

    def test_doctor_warns_for_broad_existing_permissions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            data_dir = os.path.join(temp_dir, "data")
            os.makedirs(data_dir)
            history_path = os.path.join(data_dir, "history.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "config": {
                            "import_ssh_config": False,
                            "encryption_enabled": True,
                            "encryption_salt": "MTIzNDU2Nzg5MDEyMzQ1Ng==",
                        },
                        "hosts": [
                            {
                                "type": "host",
                                "name": "encrypted",
                                "host": "example.com",
                                "user": "deploy",
                                "password": "ciphertext",
                            }
                        ],
                    },
                    f,
                )
            with open(history_path, "w", encoding="utf-8") as f:
                f.write("{}\n")
            os.chmod(path, 0o644)
            os.chmod(data_dir, 0o755)
            os.chmod(history_path, 0o644)

            stdout = StringIO()
            with redirect_stdout(stdout):
                code = cli_diagnostics.run_doctor_for_path(
                    path,
                    data_dir=data_dir,
                    tui_cls=self._doctor_tui_cls(True),
                    which=self._which_all(),
                )

            output = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("[WARN] Config permissions", output)
            self.assertIn("[WARN] Runtime data dir permissions", output)
            self.assertIn("[WARN] history.jsonl permissions", output)

    def test_doctor_for_path_accepts_explicit_host_manager_dependency(self):
        class FakeAudit:
            data_dir = ""

        class FakeHostManager:
            constructed = False

            def __init__(self, config_path, data_dir=None, auto_migrate=False):
                FakeHostManager.constructed = True
                self.config = {
                    "import_ssh_config": False,
                    "tui_screen_policy": "isolated",
                }
                self.audit = FakeAudit()
                self.audit.data_dir = data_dir

        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_legacy_config(temp_dir)
            data_dir = os.path.join(temp_dir, "data")
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = cli_diagnostics.run_doctor_for_path(
                    path,
                    data_dir=data_dir,
                    host_manager_cls=FakeHostManager,
                    tui_cls=self._doctor_tui_cls(True),
                    which=self._which_all(),
                )

            self.assertTrue(FakeHostManager.constructed)
            self.assertEqual(code, 0)
            self.assertIn("[PASS] Runtime data dir", stdout.getvalue())

    def test_run_tui_preserves_constructor_failure(self):
        class FakeManager:
            def get_hosts(self):
                return [{"type": "host", "name": "demo"}]

        real_tui = sshgo_module.Tui

        def fake_tui(*args, **kwargs):
            raise RuntimeError("curses init failed")

        sshgo_module.Tui = fake_tui
        try:
            with self.assertRaisesRegex(RuntimeError, "curses init failed"):
                sshgo_module.run_tui(FakeManager())
        finally:
            sshgo_module.Tui = real_tui

    def test_run_tui_empty_config_uses_flow_helper(self):
        events = []

        class FakeManager:
            def get_hosts(self):
                return []

        class FakeTui:
            def __init__(self, host_manager, mode="connect"):
                events.append(("init", mode))

            def restore_screen(self):
                events.append(("restore",))

        real_tui = sshgo_module.Tui
        real_input = builtins.input
        real_run_add_flow = sshgo_module.tui_flows.run_add_flow
        prompts = []
        sshgo_module.Tui = FakeTui

        def fake_input(prompt):
            prompts.append(prompt)
            return "y"

        builtins.input = fake_input
        sshgo_module.tui_flows.run_add_flow = lambda tui: events.append(("add",))
        try:
            with redirect_stdout(StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    sshgo_module.run_tui(FakeManager())
        finally:
            sshgo_module.Tui = real_tui
            builtins.input = real_input
            sshgo_module.tui_flows.run_add_flow = real_run_add_flow

        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(events, [("init", "add"), ("add",), ("restore",)])
        self.assertEqual(prompts, [sshgo_module.i18n.get("first_run_add_prompt")])

if __name__ == "__main__":
    unittest.main()
