import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import host_manager as host_manager_module
import sshgo as sshgo_module
from host_manager import HostManager


class CliTests(unittest.TestCase):
    def _manager(self, temp_dir):
        config = {
            "config": {"import_ssh_config": False},
            "hosts": [
                {
                    "type": "host",
                    "name": "jump",
                    "host": "jump.example.com:2200",
                    "user": "jumpuser",
                    "password": "jump-pass",
                    "id_file": "/tmp/jump_key",
                    "mfa_secret": "JBSWY3DPEHPK3PXP",
                    "children": [
                        {
                            "type": "host",
                            "name": "target",
                            "host": "target.internal:2222",
                            "user": "targetuser",
                            "password": "target-pass",
                            "id_file": "/tmp/target_key",
                            "mfa_secret": "JBSWY3DPEHPK3PXP",
                        }
                    ],
                }
            ],
        }
        path = os.path.join(temp_dir, "hosts.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f)
        return HostManager(path, data_dir=os.path.join(temp_dir, "data"))

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
                    sshgo_module._default_config_path(script_dir),
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
                    sshgo_module._default_config_path(script_dir),
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
            real_which = sshgo_module.shutil.which
            sshgo_module.shutil.which = lambda name: "/usr/bin/expect"
            try:
                stdout = StringIO()
                with redirect_stdout(stdout):
                    code = sshgo_module.run_doctor(manager, manager.json_path)
            finally:
                sshgo_module.shutil.which = real_which

            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("[PASS] Config validation", output)
            self.assertIn("[PASS] expect", output)
            self.assertIn("Runtime data dir", output)

    def test_doctor_reports_malformed_config_without_host_manager_load(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("{bad json")

            real_which = sshgo_module.shutil.which
            real_host_manager = sshgo_module.HostManager
            sshgo_module.shutil.which = lambda name: "/usr/bin/expect"
            sshgo_module.HostManager = lambda *args, **kwargs: self.fail(
                "malformed config should not construct HostManager"
            )
            try:
                stdout = StringIO()
                with redirect_stdout(stdout):
                    code = sshgo_module.run_doctor_for_path(
                        path,
                        data_dir=os.path.join(temp_dir, "data"),
                    )
            finally:
                sshgo_module.shutil.which = real_which
                sshgo_module.HostManager = real_host_manager

            output = stdout.getvalue()
            self.assertEqual(code, 1)
            self.assertIn("[PASS] Config path", output)
            self.assertIn("[FAIL] Config validation", output)
            self.assertIn("[PASS] expect", output)
            self.assertIn("Runtime data dir", output)

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

    def test_run_edit_tui_restores_screen_on_failure(self):
        events = []

        class FakeTui:
            def __init__(self, host_manager, mode="connect"):
                events.append(("init", mode))

            def run(self):
                events.append(("run",))
                raise RuntimeError("edit failed")

            def restore_screen(self):
                events.append(("restore",))

        real_tui = sshgo_module.Tui
        sshgo_module.Tui = FakeTui
        try:
            with self.assertRaisesRegex(RuntimeError, "edit failed"):
                sshgo_module.run_edit_tui(object())
        finally:
            sshgo_module.Tui = real_tui

        self.assertEqual(events, [("init", "edit"), ("run",), ("restore",)])


if __name__ == "__main__":
    unittest.main()
