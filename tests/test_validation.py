import json
import os
import tempfile
import unittest

from config_validation import validate_hosts_config
from host_manager import HostManager

try:
    from fixtures import jump_with_target, manager_for_config
except ImportError:
    from tests.fixtures import jump_with_target, manager_for_config


class ValidationTests(unittest.TestCase):
    def _manager(self, temp_dir):
        return manager_for_config(temp_dir, hosts=[jump_with_target()])

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

    def test_global_agent_does_not_satisfy_shell_or_relay_target_auth(self):
        errors = validate_hosts_config(
            {
                "config": {
                    "use_ssh_agent": True,
                    "default_ssh_jump_mode": "shell",
                    "default_transfer_jump_mode": "relay",
                },
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
                            }
                        ],
                    }
                ],
            }
        )

        joined = "\n".join(errors)
        self.assertIn("cannot rely on global use_ssh_agent", joined)
        self.assertIn("ssh_jump_mode=shell", joined)
        self.assertIn("transfer_jump_mode=relay", joined)

    def test_missing_shell_target_auth_without_global_agent_uses_generic_error(self):
        errors = validate_hosts_config(
            {
                "config": {"default_ssh_jump_mode": "shell"},
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
                            }
                        ],
                    }
                ],
            }
        )

        joined = "\n".join(errors)
        self.assertIn("No auth method configured", joined)
        self.assertNotIn("cannot rely on global use_ssh_agent", joined)

    def test_global_agent_satisfies_tunnel_target_auth(self):
        errors = validate_hosts_config(
            {
                "config": {
                    "use_ssh_agent": True,
                    "default_ssh_jump_mode": "tunnel",
                    "default_transfer_jump_mode": "tunnel",
                },
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
                            }
                        ],
                    }
                ],
            }
        )

        self.assertEqual(errors, [])

    def test_explicit_agent_satisfies_shell_or_relay_target_auth(self):
        errors = validate_hosts_config(
            {
                "config": {
                    "default_ssh_jump_mode": "shell",
                    "default_transfer_jump_mode": "relay",
                },
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
                                "use_ssh_agent": True,
                            }
                        ],
                    }
                ],
            }
        )

        self.assertEqual(errors, [])

    def test_validation_reports_identity_schema_and_port_errors(self):
        errors = validate_hosts_config(
            {
                "config": {},
                "hosts": [
                    {
                        "id": "duplicate-id",
                        "type": "host",
                        "name": "duplicate-name",
                        "host": "example.com",
                        "port": "70000",
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

    def test_validation_accepts_ipv6_endpoint_forms(self):
        errors = validate_hosts_config(
            {
                "config": {},
                "hosts": [
                    {
                        "type": "host",
                        "name": "ipv6-default",
                        "host": "2001:db8::1",
                        "user": "deploy",
                        "password": "pw",
                    },
                    {
                        "type": "host",
                        "name": "ipv6-port",
                        "host": "2001:db8::2",
                        "port": "2222",
                        "user": "deploy",
                        "password": "pw",
                    },
                ],
            }
        )

        self.assertEqual(errors, [])

    def test_validation_rejects_malformed_ipv6_endpoint(self):
        errors = validate_hosts_config(
            {
                "config": {},
                "hosts": [
                    {
                        "type": "host",
                        "name": "bad-ipv6",
                        "host": "[2001:db8::1:2222",
                        "user": "deploy",
                        "password": "pw",
                    }
                ],
            }
        )

        self.assertIn("Invalid host endpoint", "\n".join(errors))

    def test_validation_rejects_invalid_unbracketed_multi_colon_endpoint(self):
        for host in ("foo:bar:baz", "example.com:abc:def", "2001:db8::zz"):
            with self.subTest(host=host):
                errors = validate_hosts_config(
                    {
                        "config": {},
                        "hosts": [
                            {
                                "type": "host",
                                "name": "bad-host",
                                "host": host,
                                "user": "deploy",
                                "password": "pw",
                            }
                        ],
                    }
                )

                self.assertIn("Invalid host endpoint", "\n".join(errors))

    def test_validation_rejects_invalid_or_missing_encryption_salt(self):
        invalid = validate_hosts_config(
            {
                "config": {
                    "encryption_salt": "not valid base64!?",
                },
                "hosts": [],
            }
        )
        self.assertIn("encryption_salt must be valid", "\n".join(invalid))

        missing = validate_hosts_config(
            {
                "config": {
                    "encryption_enabled": True,
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
            }
        )
        self.assertIn("encryption_salt is required", "\n".join(missing))

    def test_validate_config_schema_rejects_invalid_known_values(self):
        errors = validate_hosts_config(
            {
                "config": {
                    "import_ssh_config": "yes",
                    "show_detail_pane": "true",
                    "audit_full": 1,
                    "use_ssh_agent": None,
                    "strict_host_key_checking": "no",
                    "show_recent": "false",
                    "recent_expanded": 0,
                    "language": "jp",
                    "data_dir": 42,
                    "encryption_salt": False,
                    "theme": {
                        "highlight_fg": "green",
                        "highlight_bg": "purple",
                        "extra": "cyan",
                    },
                },
                "hosts": [],
            }
        )

        joined = "\n".join(errors)
        self.assertIn("config.import_ssh_config must be true or false", joined)
        self.assertIn("config.audit_full must be true or false", joined)
        self.assertIn("config.show_recent must be true or false", joined)
        self.assertIn("Invalid language: jp", joined)
        self.assertIn("config.data_dir must be a string or null", joined)
        self.assertIn("config.encryption_salt must be a string or null", joined)
        self.assertIn("Invalid theme color for highlight_bg: purple", joined)
        self.assertIn("Unknown theme field: extra", joined)

    def test_validate_config_schema_allows_unknown_config_keys(self):
        errors = validate_hosts_config(
            {
                "config": {
                    "custom_note": {"owner": "personal"},
                    "theme": {
                        "highlight_fg": "green",
                        "highlight_bg": "default",
                        "prefix_color": "cyan",
                    },
                },
                "hosts": [],
            }
        )

        self.assertEqual(errors, [])

    def test_validate_tui_screen_policy(self):
        for policy in ("isolated", "private"):
            with self.subTest(policy=policy):
                errors = validate_hosts_config(
                    {
                        "config": {"tui_screen_policy": policy},
                        "hosts": [],
                    }
                )
                self.assertEqual(errors, [])

        invalid = validate_hosts_config(
            {
                "config": {"tui_screen_policy": "inline"},
                "hosts": [],
            }
        )
        self.assertIn("Invalid tui_screen_policy: inline", "\n".join(invalid))

        for policy in ([], {}, None):
            with self.subTest(policy=policy):
                invalid_type = validate_hosts_config(
                    {
                        "config": {"tui_screen_policy": policy},
                        "hosts": [],
                    }
                )
                joined = "\n".join(invalid_type)
                self.assertIn("config.tui_screen_policy must be a string", joined)
                self.assertIn("Invalid tui_screen_policy", joined)

    def test_validate_terminal_title_options(self):
        errors = validate_hosts_config(
            {
                "config": {
                    "terminal_title_enabled": True,
                    "terminal_title_target": "both",
                    "terminal_title_format": "alias_host",
                    "terminal_title_scope": "always",
                },
                "hosts": [],
            }
        )
        self.assertEqual(errors, [])

        invalid = validate_hosts_config(
            {
                "config": {
                    "terminal_title_enabled": "yes",
                    "terminal_title_target": "pane",
                    "terminal_title_format": "template",
                    "terminal_title_scope": "tty",
                },
                "hosts": [],
            }
        )
        joined = "\n".join(invalid)
        self.assertIn("config.terminal_title_enabled must be true or false", joined)
        self.assertIn("Invalid terminal_title_target: pane", joined)
        self.assertIn("Invalid terminal_title_format: template", joined)
        self.assertIn("Invalid terminal_title_scope: tty", joined)

    def test_validation_rejects_unsupported_deep_host_nesting(self):
        errors = validate_hosts_config(
            {
                "config": {},
                "hosts": [
                    {
                        "type": "host",
                        "name": "jump-one",
                        "host": "jump-one.example.com",
                        "user": "jump",
                        "password": "pw",
                        "children": [
                            {
                                "type": "host",
                                "name": "jump-two",
                                "host": "jump-two.example.com",
                                "user": "jump",
                                "password": "pw",
                                "children": [
                                    {
                                        "type": "host",
                                        "name": "target",
                                        "host": "target.example.com",
                                        "user": "target",
                                        "password": "pw",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )

        self.assertIn("Unsupported nested host topology", "\n".join(errors))

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

    def test_validate_proxy_command_and_placeholders(self):
        valid = validate_hosts_config(
            {
                "config": {
                    "placeholders": {
                        "site_domain": "example.net",
                        "user": "root",
                        "proxy": "127.0.0.1:1080",
                        "relay_dir": "/tmp",
                    },
                    "relay_temp_dir": "{{relay_dir}}",
                },
                "hosts": [
                    {
                        "type": "host",
                        "name": "demo-host",
                        "host": "ssh.{{site_domain}}",
                        "user": "{{user}}",
                        "password": "pw",
                        "proxy_command": "nc -X 5 -x {{proxy}} %h %p",
                    }
                ],
            }
        )
        self.assertEqual(valid, [])

        invalid = validate_hosts_config(
            {
                "config": {
                    "placeholders": {
                        "bad-name": "value",
                        "empty": "",
                        "proxy": "127.0.0.1:1080",
                    },
                    "relay_temp_dir": "{{missing_relay_dir}}",
                },
                "hosts": [
                    {
                        "type": "group",
                        "name": "bad-group",
                        "proxy_command": "nc %h %p",
                    },
                    {
                        "type": "host",
                        "name": "empty-proxy",
                        "host": "example.com",
                        "user": "deploy",
                        "password": "pw",
                        "proxy_command": "",
                    },
                    {
                        "type": "host",
                        "name": "missing-placeholder",
                        "host": "{{missing_host}}",
                        "user": "deploy",
                        "password": "pw",
                        "proxy_command": "nc -x {{proxy}} %h %p",
                    },
                    {
                        "type": "host",
                        "name": "bad-placeholder-syntax",
                        "host": "example.net",
                        "user": "deploy",
                        "password": "pw",
                        "proxy_command": "nc -x {{bad-name}} %h %p",
                    },
                    {
                        "type": "host",
                        "name": "missing-close-brace",
                        "host": "bad.{{home_domain:22",
                        "user": "deploy",
                        "password": "pw",
                    },
                    {
                        "type": "host",
                        "name": "missing-open-brace",
                        "host": "bad.home_domain}}:22",
                        "user": "deploy",
                        "password": "pw",
                    },
                    {
                        "type": "host",
                        "name": "jump",
                        "host": "jump.example.com",
                        "user": "jump",
                        "password": "pw",
                        "children": [
                            {
                                "type": "host",
                                "name": "nested",
                                "host": "nested.example.com",
                                "user": "nested",
                                "password": "pw",
                                "proxy_command": "nc -x {{proxy}} %h %p",
                            }
                        ],
                    },
                ],
            }
        )
        joined = "\n".join(invalid)
        self.assertIn("Invalid placeholder name", joined)
        self.assertIn("Invalid placeholder value", joined)
        self.assertIn("Unknown placeholder", joined)
        self.assertIn("only allowed on host", joined)
        self.assertIn("Invalid proxy_command", joined)
        self.assertIn("nested jump host modes", joined)

    def test_default_placeholders_do_not_share_mutable_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path1 = os.path.join(temp_dir, "one.json")
            path2 = os.path.join(temp_dir, "two.json")
            for path in (path1, path2):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump({"config": {"import_ssh_config": False}, "hosts": []}, f)

            first = HostManager(path1, data_dir=os.path.join(temp_dir, "data1"))
            second = HostManager(path2, data_dir=os.path.join(temp_dir, "data2"))
            first.config["placeholders"]["leak"] = "value"

            self.assertNotIn("leak", second.config["placeholders"])

    def test_default_load_does_not_persist_node_id_migration(self):
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
            )
            self.assertTrue(manager.find_host_by_alias("legacy").get("id"))
            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertNotIn("id", saved["hosts"][0])
            self.assertFalse(os.path.exists(path + ".bak"))

    def test_explicit_node_id_migration_persists_ids(self):
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

            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))
            self.assertTrue(manager.persist_node_id_migration_if_needed())

            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertIn("id", saved["hosts"][0])
            self.assertTrue(os.path.exists(path + ".bak"))
            self.assertFalse(manager.persist_node_id_migration_if_needed())

    def test_validate_add_candidate_rejects_invalid_nodes_without_mutating_tree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")

            duplicate_errors = manager.validate_add_candidate(
                {
                    "type": "host",
                    "name": "target",
                    "host": "new-target.internal",
                    "user": "deploy",
                    "password": "pw",
                }
            )
            self.assertIn("Duplicate node name", "\n".join(duplicate_errors))

            port_errors = manager.validate_add_candidate(
                {
                    "type": "host",
                    "name": "bad-port",
                    "host": "bad.internal",
                    "port": "70000",
                    "user": "deploy",
                    "password": "pw",
                }
            )
            self.assertIn("Port '70000'", "\n".join(port_errors))

            nested_errors = manager.validate_add_candidate(
                {
                    "type": "host",
                    "name": "too-deep",
                    "host": "deep.internal",
                    "user": "deploy",
                    "password": "pw",
                },
                parent_name="target",
            )
            self.assertIn(
                "Unsupported nested host topology",
                "\n".join(nested_errors),
            )
            self.assertNotIn("children", target)

    def test_validate_update_candidate_rejects_bad_port_without_mutating_node(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")

            errors = manager.validate_update_candidate(
                "target",
                {
                    "name": "target",
                    "host": "target.internal",
                    "port": "70000",
                    "user": "targetuser",
                    "auth": "password",
                    "password": "target-pass",
                    "id_file": "",
                    "mfa_secret": "",
                    "ssh_jump_mode": "default",
                    "transfer_jump_mode": "default",
                },
            )

            self.assertIn("Port '70000'", "\n".join(errors))
            self.assertEqual(target["host"], "target.internal")
            self.assertEqual(target["port"], "2222")
            self.assertEqual(target["id_file"], "/tmp/target_key")


if __name__ == "__main__":
    unittest.main()
