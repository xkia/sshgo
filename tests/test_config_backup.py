import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import sshgo as sshgo_module
from host_manager import HostManager


class ConfigBackupTests(unittest.TestCase):
    def _write_config(self, path, name):
        config = {
            "config": {"import_ssh_config": False},
            "hosts": [
                {
                    "type": "host",
                    "name": name,
                    "host": f"{name}.example.com",
                    "user": "deploy",
                    "password": "pw",
                }
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f)
            f.write("\n")

    def _host_names(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return [host["name"] for host in json.load(f)["hosts"]]

    def test_list_config_backups_reports_existing_rotation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            self._write_config(path, "current")
            self._write_config(path + ".bak", "backup")

            backups = HostManager.list_config_backups(path)

            self.assertEqual([backup["index"] for backup in backups], [0])
            self.assertEqual(backups[0]["path"], path + ".bak")
            self.assertGreater(backups[0]["size"], 0)
            self.assertIn("T", backups[0]["mtime"])

    def test_restore_config_backup_preserves_current_as_newest_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            self._write_config(path, "current")
            self._write_config(path + ".bak", "backup")

            result = HostManager.restore_config_backup(path, 0)

            self.assertEqual(result["target"], path)
            self.assertEqual(self._host_names(path), ["backup"])
            self.assertEqual(self._host_names(path + ".bak"), ["current"])
            self.assertEqual(self._host_names(path + ".bak.1"), ["backup"])

    def test_restore_config_backup_works_when_current_config_is_malformed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("{bad json")
            self._write_config(path + ".bak", "backup")

            HostManager.restore_config_backup(path, 0)

            self.assertEqual(self._host_names(path), ["backup"])
            with open(path + ".bak", "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "{bad json")

    def test_restore_config_backup_rejects_invalid_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            self._write_config(path, "current")
            with open(path + ".bak", "w", encoding="utf-8") as f:
                f.write("{bad json")

            with self.assertRaisesRegex(ValueError, "Backup is not valid JSON"):
                HostManager.restore_config_backup(path, 0)

            self.assertEqual(self._host_names(path), ["current"])

    def test_cli_backup_helpers_list_and_report_restore_errors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            self._write_config(path, "current")
            self._write_config(path + ".bak", "backup")

            stdout = StringIO()
            with redirect_stdout(stdout):
                code = sshgo_module.show_config_backups(path)
            self.assertEqual(code, 0)
            rendered = stdout.getvalue()
            self.assertIn("Config backups", rendered)
            self.assertIn("[0]", rendered)
            self.assertIn(path + ".bak", rendered)

            stderr = StringIO()
            with redirect_stderr(stderr):
                code = sshgo_module.restore_config_backup(path, 2)
            self.assertEqual(code, 1)
            self.assertIn("Backup not found", stderr.getvalue())

    def test_cli_backup_helpers_use_sshgo_host_manager_binding(self):
        class FakeHostManager:
            @staticmethod
            def list_config_backups(config_path):
                return [
                    {
                        "index": 0,
                        "path": config_path + ".fake",
                        "size": 12,
                        "mtime": "now",
                    }
                ]

            @staticmethod
            def restore_config_backup(config_path, index):
                return {
                    "index": index,
                    "source": config_path + ".fake",
                    "target": config_path,
                }

        real_host_manager = sshgo_module.HostManager
        sshgo_module.HostManager = FakeHostManager
        try:
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = sshgo_module.show_config_backups("/tmp/hosts.json")
            self.assertEqual(code, 0)
            self.assertIn("/tmp/hosts.json.fake", stdout.getvalue())

            stdout = StringIO()
            with redirect_stdout(stdout):
                code = sshgo_module.restore_config_backup("/tmp/hosts.json", 0)
            self.assertEqual(code, 0)
            self.assertIn("/tmp/hosts.json.fake", stdout.getvalue())
        finally:
            sshgo_module.HostManager = real_host_manager


if __name__ == "__main__":
    unittest.main()
