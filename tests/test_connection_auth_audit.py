import json
import os
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
                        manager.execute_sftp_transfer(
                            target, "upload", "local.txt", "/tmp/remote.txt"
                        )
            finally:
                host_manager_module.SCRIPT_DIR = old_script_dir

            with open(manager.audit.audit_simple_path, "r", encoding="utf-8") as f:
                records = [json.loads(line) for line in f if line.strip()]
            self.assertTrue(any(r["result"] == "sftp_started" for r in records))
            self.assertTrue(any(r["result"] == "sftp_exp_not_found" for r in records))

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


if __name__ == "__main__":
    unittest.main()
