import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO

import host_manager as host_manager_module
import sshgo as sshgo_module
from audit_logger import AuditLogger
from host_manager import HostManager, validate_hosts_config
from tui import Tui


class ConnectionAuthAuditTests(unittest.TestCase):
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

    def test_target_and_jump_auth_are_independent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")

            captured = {}
            real_execve = host_manager_module.os.execve

            def fake_execve(path, args, env):
                captured["args"] = args
                captured["env"] = env
                raise OSError(5, "fake")

            host_manager_module.os.execve = fake_execve
            try:
                with redirect_stderr(StringIO()):
                    with self.assertRaises(SystemExit):
                        manager.execute_interactive_connection(target, "uptime")
            finally:
                host_manager_module.os.execve = real_execve

            args = captured["args"]
            env = captured["env"]
            self.assertEqual(args[args.index("-i") + 1], "/tmp/target_key")
            self.assertEqual(args[args.index("-j-i") + 1], "/tmp/jump_key")
            self.assertEqual(env["SSHGO_TARGET_PASS"], "target-pass")
            self.assertEqual(env["SSHGO_JUMPER_PASS"], "jump-pass")
            self.assertEqual(env["SSHGO_MFA_SECRET"], "JBSWY3DPEHPK3PXP")
            self.assertEqual(env["SSHGO_JUMPER_MFA_SECRET"], "JBSWY3DPEHPK3PXP")

    def test_login_exp_supports_shell_and_tunnel_jump_modes(self):
        with open("login.exp", "r", encoding="utf-8") as f:
            script = f.read()

        self.assertIn("set connection_stage \"jumper\"", script)
        self.assertIn("target_ssh_command", script)
        self.assertIn("set jump_mode \"shell\"", script)
        self.assertIn("ProxyCommand", script)
        self.assertIn("-W %h:%p", script)

    def test_ssh_tunnel_mode_is_passed_to_expect(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")
            target["ssh_jump_mode"] = "tunnel"

            captured = {}
            real_execve = host_manager_module.os.execve

            def fake_execve(path, args, env):
                captured["args"] = args
                raise OSError(5, "fake")

            host_manager_module.os.execve = fake_execve
            try:
                with redirect_stderr(StringIO()):
                    with self.assertRaises(SystemExit):
                        manager.execute_interactive_connection(target)
            finally:
                host_manager_module.os.execve = real_execve

            args = captured["args"]
            self.assertEqual(args[args.index("-jump-mode") + 1], "tunnel")

    def test_target_agent_does_not_suppress_jump_password(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")
            target["use_ssh_agent"] = True

            old_sock = os.environ.get("SSH_AUTH_SOCK")
            os.environ["SSH_AUTH_SOCK"] = "/tmp/fake-agent.sock"
            captured = {}
            real_execve = host_manager_module.os.execve

            def fake_execve(path, args, env):
                captured["env"] = env
                raise OSError(5, "fake")

            host_manager_module.os.execve = fake_execve
            try:
                with redirect_stderr(StringIO()):
                    with self.assertRaises(SystemExit):
                        manager.execute_interactive_connection(target)
            finally:
                host_manager_module.os.execve = real_execve
                if old_sock is None:
                    os.environ.pop("SSH_AUTH_SOCK", None)
                else:
                    os.environ["SSH_AUTH_SOCK"] = old_sock

            self.assertNotIn("SSHGO_TARGET_PASS", captured["env"])
            self.assertEqual(captured["env"]["SSHGO_JUMPER_PASS"], "jump-pass")

    def test_global_agent_satisfies_validation_auth(self):
        errors = validate_hosts_config(
            {
                "config": {"use_ssh_agent": True},
                "hosts": [
                    {
                        "type": "host",
                        "name": "agent-only",
                        "host": "example.com",
                        "user": "deploy",
                    }
                ],
            }
        )
        self.assertEqual(errors, [])

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

    def test_save_hosts_writes_valid_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            manager.config["language"] = "zh"
            manager._save_hosts()

            with open(manager.json_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["config"]["language"], "zh")

    def test_node_ids_are_saved_and_preserved_on_rename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")
            original_id = target.get("id")
            self.assertTrue(original_id)

            manager.update_node(
                "target",
                {
                    "name": "renamed-target",
                    "host": "target.internal:2222",
                    "user": "targetuser",
                },
            )
            renamed = manager.find_host_by_alias("renamed-target")
            self.assertEqual(renamed.get("id"), original_id)

            with open(manager.json_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            saved_target = saved["hosts"][0]["children"][0]
            self.assertEqual(saved_target["id"], original_id)

    def test_validate_style_load_does_not_persist_node_id_migration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
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
            }
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)

            manager = HostManager(
                path,
                data_dir=os.path.join(temp_dir, "data"),
                auto_migrate=False,
            )
            self.assertTrue(manager.find_host_by_alias("legacy").get("id"))
            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertNotIn("id", saved["hosts"][0])
            self.assertFalse(os.path.exists(path + ".bak"))

    def test_save_hosts_creates_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            for suffix in (".bak", ".bak.1", ".bak.2"):
                try:
                    os.unlink(manager.json_path + suffix)
                except FileNotFoundError:
                    pass

            manager.config["language"] = "zh"
            manager._save_hosts()

            self.assertTrue(os.path.exists(manager.json_path + ".bak"))
            with open(manager.json_path + ".bak", "r", encoding="utf-8") as f:
                backup = json.load(f)
            self.assertIn("hosts", backup)

    def test_audit_trim_is_batched(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audit = AuditLogger(temp_dir)
            audit.HISTORY_MAX = 3
            audit.AUDIT_SIMPLE_MAX = 3
            audit.TRIM_BATCH = 2

            for i in range(5):
                audit.record_login(str(i), "host", "user", "none", "started")
            with open(audit.history_path, "r", encoding="utf-8") as f:
                self.assertEqual(sum(1 for _ in f), 5)

            audit.record_login("5", "host", "user", "none", "started")
            with open(audit.history_path, "r", encoding="utf-8") as f:
                self.assertEqual(sum(1 for _ in f), 3)

    def test_sftp_exec_failure_is_audited(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")

            old_script_dir = host_manager_module.SCRIPT_DIR
            host_manager_module.SCRIPT_DIR = os.path.join(temp_dir, "missing")
            try:
                with redirect_stderr(StringIO()):
                    with self.assertRaises(SystemExit):
                        manager.execute_file_transfer(
                            target, "upload", "local.txt", "/tmp/remote.txt"
                        )
            finally:
                host_manager_module.SCRIPT_DIR = old_script_dir

            with open(manager.audit.audit_simple_path, "r", encoding="utf-8") as f:
                records = [json.loads(line) for line in f if line.strip()]
            self.assertTrue(any(r["result"] == "sftp_started" for r in records))
            self.assertTrue(any(r["result"] == "sftp_exp_not_found" for r in records))

    def test_sftp_download_maps_remote_and_local_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")

            args = manager.build_file_transfer_command_args(
                target, "download", "/remote/file.txt", "local-file.txt"
            )

        self.assertEqual(args[args.index("-action") + 1], "download")
        self.assertEqual(args[args.index("-local") + 1], "local-file.txt")
        self.assertEqual(args[args.index("-remote") + 1], "/remote/file.txt")

    def test_legacy_sftp_transfer_api_delegates_to_file_transfer_api(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")

            file_args = manager.build_file_transfer_command_args(
                target, "upload", "local-file.txt", "/remote/file.txt"
            )
            legacy_args = manager.build_sftp_command_args(
                target, "upload", "local-file.txt", "/remote/file.txt"
            )

        self.assertEqual(file_args, legacy_args)

    def test_relay_transfer_uses_relay_expect_script(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")
            target["transfer_jump_mode"] = "relay"

            captured = {}
            real_execve = host_manager_module.os.execve

            def fake_execve(path, args, env):
                captured["path"] = path
                captured["args"] = args
                captured["env"] = env
                raise OSError(5, "fake")

            host_manager_module.os.execve = fake_execve
            try:
                with redirect_stderr(StringIO()):
                    with self.assertRaises(SystemExit):
                        manager.execute_file_transfer(
                            target, "upload", "local.txt", "/tmp/remote.txt"
                        )
            finally:
                host_manager_module.os.execve = real_execve

            self.assertTrue(captured["path"].endswith("relay_transfer.exp"))
            args = captured["args"]
            self.assertIn("-temp", args)
            self.assertEqual(args[args.index("-J-host") + 1], "jump.example.com")
            self.assertEqual(args[args.index("-J-port") + 1], "2200")
            self.assertEqual(args[args.index("-i") + 1], "/tmp/target_key")
            self.assertEqual(args[args.index("-j-i") + 1], "/tmp/jump_key")
            self.assertEqual(captured["env"]["SSHGO_TARGET_PASS"], "target-pass")
            self.assertEqual(captured["env"]["SSHGO_JUMPER_PASS"], "jump-pass")

            with open(manager.audit.audit_simple_path, "r", encoding="utf-8") as f:
                records = [json.loads(line) for line in f if line.strip()]
            self.assertTrue(
                any(r["result"] == "relay_upload_started" for r in records)
            )
            self.assertTrue(
                any(r["result"] == "relay_exec_failed:5" for r in records)
            )

    def test_relay_download_maps_remote_and_local_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")
            target["transfer_jump_mode"] = "relay"

            args, _ = manager._build_relay_command_parts(
                target, "download", "/remote/file.txt", "local-file.txt"
            )

        self.assertEqual(args[args.index("-action") + 1], "download")
        self.assertEqual(args[args.index("-local") + 1], "local-file.txt")
        self.assertEqual(args[args.index("-remote") + 1], "/remote/file.txt")

    def test_relay_transfer_quotes_paths_and_target_host_key_options(self):
        cmd = [
            "./relay_transfer.exp",
            "-h",
            "target.example.com",
            "-u",
            "targetuser",
            "-P",
            "2222",
            "-J-host",
            "jump.example.com",
            "-J-user",
            "jumpuser",
            "-J-port",
            "2200",
            "-i",
            "/remote/key with space",
            "-j-i",
            "/local/jump key",
            "-action",
            "upload",
            "-local",
            "local file;name $x.txt",
            "-remote",
            "/tmp/remote file;name $x.txt",
            "-temp",
            "/tmp/relay temp'a&b.txt",
            "-host-key-checking",
            "no",
            "-print-command",
            "target-upload",
        ]
        result = subprocess.run(
            cmd,
            cwd=os.getcwd(),
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        rendered = result.stdout.strip()
        self.assertIn("'scp'", rendered)
        self.assertIn("'StrictHostKeyChecking=no'", rendered)
        self.assertIn("'UserKnownHostsFile=/dev/null'", rendered)
        self.assertIn("'/remote/key with space'", rendered)
        self.assertIn("'/tmp/relay temp'\\''a&b.txt'", rendered)
        self.assertIn(
            "'targetuser@target.example.com:/tmp/remote file;name $x.txt'",
            rendered,
        )

    def test_relay_transfer_quotes_double_quote_backslash_and_newline(self):
        remote_path = "/tmp/remote \"quote\" \\ slash\nline.txt"
        temp_path = "/tmp/relay \"quote\" \\ slash\nline.txt"
        cmd = [
            "./relay_transfer.exp",
            "-h",
            "target.example.com",
            "-u",
            "targetuser",
            "-J-host",
            "jump.example.com",
            "-J-user",
            "jumpuser",
            "-action",
            "upload",
            "-local",
            "local.txt",
            "-remote",
            remote_path,
            "-temp",
            temp_path,
            "-print-command",
            "target-upload",
        ]
        result = subprocess.run(
            cmd,
            cwd=os.getcwd(),
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        rendered = result.stdout
        self.assertIn("'scp'", rendered)
        self.assertIn(temp_path, rendered)
        self.assertIn(f"'targetuser@target.example.com:{remote_path}'", rendered)

    def test_relay_transfer_reports_cleanup_warning_without_masking_failure(self):
        with open("relay_transfer.exp", "r", encoding="utf-8") as f:
            script = f.read()

        self.assertIn("proc wait_exit_status", script)
        self.assertIn("Warning: unexpected process wait result", script)
        self.assertIn("proc can_retry_legacy_scp", script)
        self.assertIn('status == "10"', script)
        self.assertIn("Warning: could not remove relay temp file", script)
        self.assertIn("Local scp failed; retrying with legacy scp protocol", script)
        self.assertIn("cleanup_temp_path $temp_path", script)
        self.assertIn("Relay upload failed while copying to jump host", script)
        self.assertIn("fail \"\\nRelay upload failed.\\n\" 1", script)
        self.assertIn("fail \"\\nRelay download failed.\\n\" 1", script)

    def test_relay_status_marker_regex_avoids_tcl_command_substitution(self):
        with open("relay_transfer.exp", "r", encoding="utf-8") as f:
            script = f.read()

        self.assertIn("set marker_pattern [format {%s:([0-9]+)} $marker]", script)
        self.assertIn("-re $marker_pattern", script)

    def test_relay_local_scp_legacy_print_command_uses_dash_o(self):
        cmd = [
            "./relay_transfer.exp",
            "-h",
            "target.example.com",
            "-u",
            "targetuser",
            "-J-host",
            "jump.example.com",
            "-J-user",
            "jumpuser",
            "-action",
            "upload",
            "-local",
            "local.txt",
            "-remote",
            "/tmp/remote.txt",
            "-temp",
            "/tmp/relay.txt",
            "-print-command",
            "local-to-jump-legacy",
        ]
        result = subprocess.run(
            cmd,
            cwd=os.getcwd(),
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        rendered = result.stdout.strip()
        self.assertIn("'-O'", rendered)
        self.assertIn("'jumpuser@jump.example.com:/tmp/relay.txt'", rendered)

    def test_relay_upload_rejects_non_regular_local_paths_before_ssh(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_dir = os.path.join(temp_dir, "local-dir")
            os.mkdir(local_dir)
            cmd = [
                "./relay_transfer.exp",
                "-h",
                "target.example.com",
                "-u",
                "targetuser",
                "-J-host",
                "jump.example.com",
                "-J-user",
                "jumpuser",
                "-action",
                "upload",
                "-local",
                local_dir,
                "-remote",
                "/tmp/remote.txt",
                "-temp",
                "/tmp/sshgo-relay-test.txt",
            ]
            result = subprocess.run(
                cmd,
                cwd=os.getcwd(),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=3,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("regular files only", result.stdout + result.stderr)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "mkfifo is not available")
    def test_relay_upload_rejects_fifo_before_ssh(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fifo_path = os.path.join(temp_dir, "pipe")
            os.mkfifo(fifo_path)
            cmd = [
                "./relay_transfer.exp",
                "-h",
                "target.example.com",
                "-u",
                "targetuser",
                "-J-host",
                "jump.example.com",
                "-J-user",
                "jumpuser",
                "-action",
                "upload",
                "-local",
                fifo_path,
                "-remote",
                "/tmp/remote.txt",
                "-temp",
                "/tmp/sshgo-relay-test.txt",
            ]
            result = subprocess.run(
                cmd,
                cwd=os.getcwd(),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=3,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("regular files only", result.stdout + result.stderr)

    def test_tui_form_reports_terminal_too_small(self):
        class FakeScreen:
            def __init__(self):
                self.messages = []

            def clear(self):
                pass

            def border(self, _):
                pass

            def getmaxyx(self):
                return (8, 20)

            def addstr(self, *args):
                if args and isinstance(args[-1], str):
                    self.messages.append(args[-1])

            def refresh(self):
                pass

        tui = object.__new__(Tui)
        tui.screen = FakeScreen()
        tui.restore_screen = lambda: None
        result = Tui._draw_form(
            tui,
            [
                {"label": "Name", "type": "text", "name": "name", "y": 3, "x": 2},
                {"label": "Save", "type": "button", "y": 19, "x": 2},
            ],
            0,
            "Test",
        )

        self.assertFalse(result)
        self.assertTrue(
            any("Terminal too" in message for message in tui.screen.messages)
        )

    def test_audit_records_node_identity_and_endpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")

            captured = {}
            real_execve = host_manager_module.os.execve

            def fake_execve(path, args, env):
                captured["args"] = args
                raise OSError(5, "fake")

            host_manager_module.os.execve = fake_execve
            try:
                with redirect_stderr(StringIO()):
                    with self.assertRaises(SystemExit):
                        manager.execute_interactive_connection(target)
            finally:
                host_manager_module.os.execve = real_execve

            with open(manager.audit.history_path, "r", encoding="utf-8") as f:
                records = [json.loads(line) for line in f if line.strip()]
            started = next(r for r in records if r["result"] == "started")
            self.assertEqual(started["node_id"], target["id"])
            self.assertEqual(started["host"], "target.internal")
            self.assertEqual(started["port"], "2222")
            self.assertEqual(started["endpoint"], "target.internal:2222")

    def test_recent_group_uses_current_name_after_rename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            manager.audit.record_login(
                "target",
                "target.internal",
                "targetuser",
                "password",
                "started",
            )
            manager.update_node(
                "target",
                {
                    "name": "renamed-target",
                    "host": "target.internal:2222",
                    "user": "targetuser",
                },
            )

            tui = object.__new__(Tui)
            tui.host_manager = manager
            tui._recent_group = None
            tui._recent_group_ts = 0

            recent_group = Tui._build_recent_group(tui)
            recent_names = [
                child["name"] for child in recent_group.get("children", [])
            ]
            self.assertIn("renamed-target", recent_names)
            self.assertNotIn("target", recent_names)

    def test_recent_group_is_collapsed_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            manager.audit.record_login(
                "target",
                "target.internal",
                "targetuser",
                "password",
                "started",
            )

            tui = object.__new__(Tui)
            tui.host_manager = manager
            tui._recent_group = None
            tui._recent_group_ts = 0

            recent_group = Tui._build_recent_group(tui)
            self.assertFalse(recent_group.get("expanded"))

    def test_recent_group_resolves_by_node_id_before_endpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "config": {"import_ssh_config": False},
                "hosts": [
                    {
                        "type": "host",
                        "name": "app-22",
                        "host": "shared.internal:22",
                        "user": "deploy",
                        "password": "pw",
                    },
                    {
                        "type": "host",
                        "name": "app-2222",
                        "host": "shared.internal:2222",
                        "user": "deploy",
                        "password": "pw",
                    },
                ],
            }
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)

            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))
            second = manager.find_host_by_alias("app-2222")
            manager.audit.record_login(
                "old-app",
                "shared.internal",
                "deploy",
                "password",
                "started",
                node_id=second["id"],
                port="2222",
                endpoint="shared.internal:2222",
            )
            manager.update_node(
                "app-2222",
                {
                    "name": "renamed-app",
                    "host": "shared.internal:2222",
                    "user": "deploy",
                },
            )

            tui = object.__new__(Tui)
            tui.host_manager = manager
            tui._recent_group = None
            tui._recent_group_ts = 0

            recent_group = Tui._build_recent_group(tui)
            recent_names = [
                child["name"] for child in recent_group.get("children", [])
            ]
            self.assertEqual(recent_names, ["renamed-app"])

    def test_validation_reports_identity_schema_and_port_errors(self):
        errors = validate_hosts_config(
            {
                "config": {},
                "hosts": [
                    {
                        "id": "duplicate-id",
                        "type": "host",
                        "name": "duplicate-name",
                        "host": "example.com:70000",
                        "user": "deploy",
                        "password": "pw",
                        "unexpected": True,
                    },
                    {
                        "id": "duplicate-id",
                        "type": "host",
                        "name": "duplicate-name",
                        "host": "example.net",
                        "user": "deploy",
                        "password": "pw",
                    },
                ],
            }
        )
        joined = "\n".join(errors)
        self.assertIn("Duplicate node name", joined)
        self.assertIn("Duplicate node id", joined)
        self.assertIn("Port '70000'", joined)
        self.assertIn("Unknown field", joined)

    def test_config_theme_is_allowed_while_node_unknown_fields_are_rejected(self):
        errors = validate_hosts_config(
            {
                "config": {
                    "theme": {
                        "highlight_fg": "white",
                        "highlight_bg": "blue",
                        "prefix_color": "red",
                    }
                },
                "hosts": [
                    {
                        "type": "host",
                        "name": "bad-node",
                        "host": "example.com",
                        "user": "deploy",
                        "password": "pw",
                        "theme": {},
                    }
                ],
            }
        )
        joined = "\n".join(errors)
        self.assertIn("Unknown field", joined)
        self.assertIn("theme", joined)

    def test_validate_jump_modes(self):
        valid = validate_hosts_config(
            {
                "config": {
                    "default_ssh_jump_mode": "shell",
                    "default_transfer_jump_mode": "tunnel",
                    "relay_temp_dir": "/tmp",
                },
                "hosts": [
                    {
                        "type": "host",
                        "name": "jump",
                        "host": "jump.example.com",
                        "user": "jump",
                        "password": "pw",
                        "transfer_jump_mode": "relay",
                        "children": [
                            {
                                "type": "host",
                                "name": "target",
                                "host": "target.example.com",
                                "user": "target",
                                "password": "pw",
                                "ssh_jump_mode": "tunnel",
                                "transfer_jump_mode": "relay",
                            }
                        ],
                    }
                ],
            }
        )
        self.assertEqual(valid, [])

        invalid = validate_hosts_config(
            {
                "config": {
                    "default_ssh_jump_mode": "bad",
                    "default_transfer_jump_mode": "bad",
                    "relay_temp_dir": "tmp",
                },
                "hosts": [
                    {
                        "type": "group",
                        "name": "bad-group",
                        "ssh_jump_mode": "shell",
                        "children": [],
                    },
                    {
                        "type": "host",
                        "name": "bad-host",
                        "host": "example.com",
                        "user": "deploy",
                        "password": "pw",
                        "ssh_jump_mode": "relay",
                        "transfer_jump_mode": "relay",
                    },
                ],
            }
        )
        joined = "\n".join(invalid)
        self.assertIn("Invalid ssh_jump_mode", joined)
        self.assertIn("Invalid transfer_jump_mode", joined)
        self.assertIn("relay_temp_dir", joined)
        self.assertIn("only allowed on host", joined)
        self.assertIn("requires a jump host", joined)


if __name__ == "__main__":
    unittest.main()
