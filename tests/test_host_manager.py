import json
import os
import tempfile
import unittest

from host_manager import HostManager


class HostManagerPersistenceCrudTests(unittest.TestCase):
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

    def test_update_node_clears_proxy_command(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "config": {"import_ssh_config": False},
                "hosts": [
                    {
                        "type": "host",
                        "name": "proxy-host",
                        "host": "example.com",
                        "user": "deploy",
                        "password": "pw",
                        "proxy_command": "nc -x 127.0.0.1:1080 %h %p",
                    }
                ],
            }
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)
            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))

            manager.update_node(
                "proxy-host",
                {
                    "name": "proxy-host",
                    "host": "example.com",
                    "user": "deploy",
                    "proxy_command": "",
                },
            )

            node = manager.find_host_by_alias("proxy-host")
            self.assertNotIn("proxy_command", node)
            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertNotIn("proxy_command", saved["hosts"][0])

    def test_add_node_drops_proxy_command_under_host_parent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "config": {"import_ssh_config": False},
                "hosts": [
                    {
                        "type": "host",
                        "name": "jump",
                        "host": "jump.example.com",
                        "user": "jumpuser",
                        "password": "pw",
                    }
                ],
            }
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)
            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))

            manager.add_node(
                {
                    "type": "host",
                    "name": "target",
                    "host": "target.internal",
                    "user": "targetuser",
                    "password": "pw",
                    "proxy_command": "nc -x 127.0.0.1:1080 %h %p",
                },
                "jump",
            )

            target = manager.find_host_by_alias("target")
            self.assertNotIn("proxy_command", target)
            self.assertEqual(target["nest_parent"]["name"], "jump")
            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertNotIn("proxy_command", saved["hosts"][0]["children"][0])

    def test_update_node_drops_proxy_command_on_nested_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "config": {"import_ssh_config": False},
                "hosts": [
                    {
                        "type": "host",
                        "name": "jump",
                        "host": "jump.example.com",
                        "user": "jumpuser",
                        "password": "pw",
                        "children": [
                            {
                                "type": "host",
                                "name": "target",
                                "host": "target.internal",
                                "user": "targetuser",
                                "password": "pw",
                                "proxy_command": "nc -x 127.0.0.1:1080 %h %p",
                            }
                        ],
                    }
                ],
            }
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)
            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))

            manager.update_node(
                "target",
                {
                    "name": "target",
                    "host": "target.internal",
                    "user": "targetuser",
                    "proxy_command": "nc -x 127.0.0.1:1081 %h %p",
                },
            )

            target = manager.find_host_by_alias("target")
            self.assertNotIn("proxy_command", target)
            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertNotIn("proxy_command", saved["hosts"][0]["children"][0])


if __name__ == "__main__":
    unittest.main()
