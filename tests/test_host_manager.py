import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO

from config_store import ConfigStore, ConfigWriteConflictError
from host_manager import HostManager

try:
    from fixtures import jump_with_target, manager_for_config
except ImportError:
    from tests.fixtures import jump_with_target, manager_for_config


class HostManagerPersistenceCrudTests(unittest.TestCase):
    def _manager(self, temp_dir):
        return manager_for_config(temp_dir, hosts=[jump_with_target()])

    def test_save_hosts_writes_valid_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            manager.config["language"] = "zh"
            manager._save_hosts()

            with open(manager.json_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["config"]["language"], "zh")

    def test_inactive_encryption_metadata_is_removed_on_save(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "config": {
                            "import_ssh_config": False,
                            "encryption_enabled": False,
                            "encryption_salt": None,
                        },
                        "hosts": [],
                    },
                    f,
                )

            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))
            self.assertNotIn("encryption_enabled", manager.config)
            self.assertTrue(manager._save_hosts())

            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertNotIn("encryption_enabled", saved["config"])
            self.assertNotIn("encryption_salt", saved["config"])

    def test_active_encryption_config_fails_before_runtime_initialization(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            data_dir = os.path.join(temp_dir, "data")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "config": {
                            "import_ssh_config": False,
                            "encryption_enabled": True,
                        },
                        "hosts": [],
                    },
                    f,
                )

            with redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    HostManager(path, data_dir=data_dir)
            self.assertEqual(cm.exception.code, 1)
            self.assertFalse(os.path.exists(data_dir))

    def test_persisted_runtime_source_fails_with_validation_error(self):
        for source in (None, 1, "ssh_config"):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as temp_dir:
                path = os.path.join(temp_dir, "hosts.json")
                data_dir = os.path.join(temp_dir, "data")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "config": {"import_ssh_config": False},
                            "hosts": [
                                {
                                    "type": "host",
                                    "name": "bad-source",
                                    "host": "example.com",
                                    "user": "deploy",
                                    "password": "pw",
                                    "source": source,
                                }
                            ],
                        },
                        f,
                    )

                stderr = StringIO()
                with redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as cm:
                        HostManager(path, data_dir=data_dir)

                self.assertEqual(cm.exception.code, 1)
                self.assertIn("source", stderr.getvalue())
                self.assertFalse(os.path.exists(data_dir))

    def test_save_refuses_invalid_node_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = manager_for_config(temp_dir, hosts=[])
            manager.hosts.append(
                {
                    "type": "group",
                    "name": "bad-group",
                    "password": "must-not-save",
                    "children": [],
                }
            )

            with redirect_stderr(StringIO()):
                self.assertFalse(manager._save_hosts())
            with open(manager.json_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["hosts"], [])

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
                    "host": "target.internal",
                            "port": "2222",
                    "user": "targetuser",
                },
            )
            renamed = manager.find_host_by_alias("renamed-target")
            self.assertEqual(renamed.get("id"), original_id)

            with open(manager.json_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            saved_target = saved["hosts"][0]["children"][0]
            self.assertEqual(saved_target["id"], original_id)

    def test_describe_host_clarifies_shell_jump_host_key_scope(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")
            target["transfer_jump_mode"] = "relay"

            details = dict(manager.describe_host(target))

            self.assertEqual(details["First Hop Host Key"], "accept-new")
            self.assertEqual(details["Target Host Key"], "managed on jump host")
            self.assertEqual(
                details["Relay Target Host Key"],
                "managed on jump host",
            )

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

    def test_stale_manager_save_does_not_overwrite_newer_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "config": {"import_ssh_config": False},
                        "hosts": [],
                    },
                    f,
                )

            stale_manager = HostManager(
                path,
                data_dir=os.path.join(temp_dir, "data-stale"),
            )
            current_manager = HostManager(
                path,
                data_dir=os.path.join(temp_dir, "data-current"),
            )

            self.assertTrue(
                current_manager.add_node(
                    {
                        "type": "host",
                        "name": "current",
                        "host": "current.example.com",
                        "user": "deploy",
                        "password": "pw",
                    },
                    None,
                )
            )
            with redirect_stderr(StringIO()):
                result = stale_manager.add_node(
                    {
                        "type": "host",
                        "name": "stale",
                        "host": "stale.example.com",
                        "user": "deploy",
                        "password": "pw",
                    },
                    None,
                )
            self.assertFalse(result)
            self.assertIn("changed in another session", stale_manager.last_save_error)

            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual([node["name"] for node in saved["hosts"]], ["current"])

    def test_write_conflict_reload_discards_failed_in_memory_mutation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "config": {"import_ssh_config": False},
                        "hosts": [],
                    },
                    f,
                )

            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))
            current_data = {
                "config": {"import_ssh_config": False},
                "hosts": [
                    {
                        "type": "host",
                        "name": "current",
                        "host": "current.example.com",
                        "user": "deploy",
                        "password": "pw",
                    }
                ],
            }

            def conflicting_write(_data, expected_fingerprint=None, check_conflict=False):
                ConfigStore(path).write_json(current_data)
                raise ConfigWriteConflictError(path)

            manager.store.write_json = conflicting_write

            with redirect_stderr(StringIO()):
                result = manager.add_node(
                    {
                        "type": "host",
                        "name": "unsaved",
                        "host": "unsaved.example.com",
                        "user": "deploy",
                        "password": "pw",
                    },
                    None,
                )

            self.assertFalse(result)
            self.assertIsNone(manager.find_host_by_alias("unsaved"))
            self.assertIsNotNone(manager.find_host_by_alias("current"))

            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual([node["name"] for node in saved["hosts"]], ["current"])

    def test_write_conflict_reload_refreshes_runtime_state_from_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            new_data_dir = os.path.join(temp_dir, "new-data")
            old_home = os.environ.get("HOME")
            old_data_dir = os.environ.pop("SSHGO_DATA_DIR", None)
            os.environ["HOME"] = temp_dir
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "config": {"import_ssh_config": False},
                            "hosts": [],
                        },
                        f,
                    )

                manager = HostManager(path)
                current_data = {
                    "config": {
                        "import_ssh_config": False,
                        "data_dir": new_data_dir,
                        "audit_full": True,
                    },
                    "hosts": [
                        {
                            "type": "host",
                            "name": "current",
                            "host": "current.example.com",
                            "user": "deploy",
                            "password": "pw",
                        }
                    ],
                }

                def conflicting_write(
                    _data,
                    expected_fingerprint=None,
                    check_conflict=False,
                ):
                    ConfigStore(path).write_json(current_data)
                    raise ConfigWriteConflictError(path)

                manager.store.write_json = conflicting_write

                with redirect_stderr(StringIO()):
                    result = manager.add_node(
                        {
                            "type": "host",
                            "name": "unsaved",
                            "host": "unsaved.example.com",
                            "user": "deploy",
                            "password": "pw",
                        },
                        None,
                    )

                self.assertFalse(result)
                self.assertEqual(manager.audit.data_dir, new_data_dir)
                self.assertTrue(manager._audit_full)
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home
                if old_data_dir is None:
                    os.environ.pop("SSHGO_DATA_DIR", None)
                else:
                    os.environ["SSHGO_DATA_DIR"] = old_data_dir

    def test_write_conflict_reload_preserves_runtime_overrides(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            override_dir = os.path.join(temp_dir, "override-data")
            config_dir = os.path.join(temp_dir, "config-data")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "config": {"import_ssh_config": False},
                        "hosts": [],
                    },
                    f,
                )

            manager = HostManager(path, data_dir=override_dir)
            manager.enable_full_audit()
            current_data = {
                "config": {
                    "import_ssh_config": False,
                    "data_dir": config_dir,
                    "audit_full": False,
                },
                "hosts": [
                    {
                        "type": "host",
                        "name": "current",
                        "host": "current.example.com",
                        "user": "deploy",
                    }
                ],
            }

            def conflicting_write(_data, expected_fingerprint=None, check_conflict=False):
                ConfigStore(path).write_json(current_data)
                raise ConfigWriteConflictError(path)

            manager.store.write_json = conflicting_write

            with redirect_stderr(StringIO()):
                result = manager.add_node(
                    {
                        "type": "host",
                        "name": "unsaved",
                        "host": "unsaved.example.com",
                        "user": "deploy",
                    },
                    None,
                )

            self.assertFalse(result)
            self.assertEqual(manager.audit.data_dir, override_dir)
            self.assertTrue(manager._audit_full)

    def test_write_conflict_reload_preserves_env_data_dir_override(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            override_dir = os.path.join(temp_dir, "env-data")
            config_dir = os.path.join(temp_dir, "config-data")
            old_data_dir = os.environ.get("SSHGO_DATA_DIR")
            os.environ["SSHGO_DATA_DIR"] = override_dir
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "config": {"import_ssh_config": False},
                            "hosts": [],
                        },
                        f,
                    )

                manager = HostManager(path)
                current_data = {
                    "config": {
                        "import_ssh_config": False,
                        "data_dir": config_dir,
                    },
                    "hosts": [
                        {
                            "type": "host",
                            "name": "current",
                            "host": "current.example.com",
                            "user": "deploy",
                        }
                    ],
                }

                def conflicting_write(
                    _data,
                    expected_fingerprint=None,
                    check_conflict=False,
                ):
                    ConfigStore(path).write_json(current_data)
                    raise ConfigWriteConflictError(path)

                manager.store.write_json = conflicting_write

                with redirect_stderr(StringIO()):
                    result = manager.add_node(
                        {
                            "type": "host",
                            "name": "unsaved",
                            "host": "unsaved.example.com",
                            "user": "deploy",
                        },
                        None,
                    )

                self.assertFalse(result)
                self.assertEqual(manager.audit.data_dir, override_dir)
            finally:
                if old_data_dir is None:
                    os.environ.pop("SSHGO_DATA_DIR", None)
                else:
                    os.environ["SSHGO_DATA_DIR"] = old_data_dir

    def test_validate_config_does_not_refresh_stale_save_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "config": {
                            "import_ssh_config": False,
                            "use_ssh_agent": True,
                        },
                        "hosts": [],
                    },
                    f,
                )

            stale_manager = HostManager(
                path,
                data_dir=os.path.join(temp_dir, "data-stale"),
            )
            current_manager = HostManager(
                path,
                data_dir=os.path.join(temp_dir, "data-current"),
            )

            self.assertTrue(
                current_manager.add_node(
                    {
                        "type": "host",
                        "name": "current",
                        "host": "current.example.com",
                        "user": "deploy",
                    },
                    None,
                )
            )
            self.assertEqual(stale_manager.validate_config(), [])
            with redirect_stderr(StringIO()):
                result = stale_manager.add_node(
                    {
                        "type": "host",
                        "name": "stale",
                        "host": "stale.example.com",
                        "user": "deploy",
                    },
                    None,
                )
            self.assertFalse(result)

            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual([node["name"] for node in saved["hosts"]], ["current"])

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

    def test_update_node_by_id_targets_selected_node_when_names_collide(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "config": {"import_ssh_config": False},
                "hosts": [
                    {
                        "id": "first",
                        "type": "host",
                        "name": "duplicate",
                        "host": "first.example.com",
                        "user": "deploy",
                        "password": "pw",
                    },
                    {
                        "id": "second",
                        "type": "host",
                        "name": "duplicate",
                        "host": "second.example.com",
                        "user": "deploy",
                        "password": "pw",
                    },
                ],
            }
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)
            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))

            manager.update_node_by_id(
                "second",
                {
                    "name": "renamed",
                    "host": "second.example.com",
                    "user": "deploy",
                },
            )

            self.assertEqual(manager.get_hosts()[0]["name"], "duplicate")
            self.assertEqual(manager.get_hosts()[1]["name"], "renamed")

    def test_delete_node_by_id_targets_selected_node_when_names_collide(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "config": {"import_ssh_config": False},
                "hosts": [
                    {
                        "id": "first",
                        "type": "group",
                        "name": "duplicate",
                        "children": [],
                    },
                    {
                        "id": "second",
                        "type": "group",
                        "name": "duplicate",
                        "children": [],
                    },
                ],
            }
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)
            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))

            manager.delete_node_by_id("second")

            self.assertEqual([node["id"] for node in manager.get_hosts()], ["first"])

    def test_add_node_to_parent_id_targets_selected_parent_when_names_collide(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "config": {"import_ssh_config": False},
                "hosts": [
                    {
                        "id": "first",
                        "type": "group",
                        "name": "duplicate",
                        "children": [],
                    },
                    {
                        "id": "second",
                        "type": "group",
                        "name": "duplicate",
                        "children": [],
                    },
                ],
            }
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)
            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))

            manager.add_node_to_parent_id(
                {
                    "type": "host",
                    "name": "child",
                    "host": "child.example.com",
                    "user": "deploy",
                    "password": "pw",
                },
                "second",
            )

            self.assertEqual(manager.get_hosts()[0]["children"], [])
            self.assertEqual(
                manager.get_hosts()[1]["children"][0]["name"],
                "child",
            )

if __name__ == "__main__":
    unittest.main()
