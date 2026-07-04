import json
import os
import tempfile
import unittest

from config_store import ConfigStore, parse_jsonc


class ConfigStoreTests(unittest.TestCase):
    def test_parse_jsonc_supports_comments_and_trailing_commas(self):
        parsed = parse_jsonc(
            """
            {
              // line comment
              "config": {"import_ssh_config": false,},
              # shell-style comment
              "hosts": [
                {
                  "type": "host",
                  "name": "demo",
                  "host": "demo.example.com",
                  "user": "deploy",
                  "password": "pw",
                },
              ],
            }
            """
        )

        self.assertFalse(parsed["config"]["import_ssh_config"])
        self.assertEqual(parsed["hosts"][0]["name"], "demo")

    def test_store_read_and_write_json_uses_backup_rotation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            store = ConfigStore(path)
            first = {
                "config": {"import_ssh_config": False},
                "hosts": [
                    {
                        "type": "host",
                        "name": "first",
                        "host": "first.example.com",
                        "user": "deploy",
                        "password": "pw",
                    }
                ],
            }
            second = {
                "config": {"import_ssh_config": False},
                "hosts": [
                    {
                        "type": "host",
                        "name": "second",
                        "host": "second.example.com",
                        "user": "deploy",
                        "password": "pw",
                    }
                ],
            }

            store.write_json(first)
            store.write_json(second)

            self.assertEqual(store.read()["hosts"][0]["name"], "second")
            with open(store.backup_path(0), "r", encoding="utf-8") as f:
                self.assertEqual(json.load(f)["hosts"][0]["name"], "first")

    def test_store_restore_backup_uses_validator(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            store = ConfigStore(path)
            current = {"config": {"import_ssh_config": False}, "hosts": []}
            backup = {
                "config": {"import_ssh_config": False},
                "hosts": [
                    {
                        "type": "host",
                        "name": "backup",
                        "host": "backup.example.com",
                        "user": "deploy",
                        "password": "pw",
                    }
                ],
            }
            store.write_json(current)
            with open(store.backup_path(0), "w", encoding="utf-8") as f:
                json.dump(backup, f)

            called = []

            def validator(data):
                called.append(data["hosts"][0]["name"])
                return []

            result = store.restore_backup(0, validate_func=validator)

            self.assertEqual(result["target"], path)
            self.assertEqual(store.read()["hosts"][0]["name"], "backup")
            self.assertEqual(called, ["backup"])


if __name__ == "__main__":
    unittest.main()
