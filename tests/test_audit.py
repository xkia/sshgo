import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO

import audit_logger as audit_logger_module
import host_manager as host_manager_module
from audit_logger import AuditLogger
from host_manager import HostManager


class AuditTests(unittest.TestCase):
    def _manager(self, temp_dir):
        config = {
            "config": {"import_ssh_config": False},
            "hosts": [
                {
                    "type": "host",
                    "name": "jump",
                    "host": "jump.example.com",
                    "port": "2200",
                    "user": "jumpuser",
                    "password": "jump-pass",
                    "id_file": "/tmp/jump_key",
                    "mfa_secret": "JBSWY3DPEHPK3PXP",
                    "children": [
                        {
                            "type": "host",
                            "name": "target",
                            "host": "target.internal",
                            "port": "2222",
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

    def test_audit_trim_uses_lock_and_atomic_replace(self):
        if audit_logger_module.fcntl is None:
            self.skipTest("fcntl is unavailable")

        with tempfile.TemporaryDirectory() as temp_dir:
            audit = AuditLogger(temp_dir)
            audit.TRIM_BATCH = 0
            for i in range(5):
                audit._append(audit.history_path, {"name": str(i)})

            lock_path = audit.history_path + ".lock"
            with open(lock_path, "a", encoding="utf-8") as lock_file:
                audit_logger_module.fcntl.flock(
                    lock_file.fileno(),
                    audit_logger_module.fcntl.LOCK_EX,
                )
                try:
                    audit._trim(audit.history_path, 3)
                    with open(audit.history_path, "r", encoding="utf-8") as f:
                        self.assertEqual(sum(1 for _ in f), 5)
                finally:
                    audit_logger_module.fcntl.flock(
                        lock_file.fileno(),
                        audit_logger_module.fcntl.LOCK_UN,
                    )

            audit._trim(audit.history_path, 3)
            with open(audit.history_path, "r", encoding="utf-8") as f:
                records = [json.loads(line) for line in f]
            self.assertEqual([record["name"] for record in records], ["2", "3", "4"])
            self.assertEqual(
                [name for name in os.listdir(temp_dir) if name.endswith(".tmp")],
                [],
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

    def test_audit_creates_private_data_dir_and_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = os.path.join(temp_dir, "data")
            audit = AuditLogger(data_dir)

            audit.record_login("demo", "example.com", "deploy", "password", "started")

            dir_mode = stat.S_IMODE(os.stat(data_dir).st_mode)
            history_mode = stat.S_IMODE(os.stat(audit.history_path).st_mode)
            audit_mode = stat.S_IMODE(os.stat(audit.audit_simple_path).st_mode)
            self.assertEqual(dir_mode & 0o077, 0)
            self.assertEqual(history_mode & 0o077, 0)
            self.assertEqual(audit_mode & 0o077, 0)


if __name__ == "__main__":
    unittest.main()
