import unittest

import config_validation
import host_manager


class ConfigValidationExtractionTests(unittest.TestCase):
    def test_host_manager_keeps_validator_compatibility_export(self):
        self.assertIs(
            host_manager.validate_hosts_config,
            config_validation.validate_hosts_config,
        )

    def test_direct_validator_accepts_valid_minimal_config(self):
        errors = config_validation.validate_hosts_config(
            {
                "config": {
                    "import_ssh_config": False,
                    "use_ssh_agent": True,
                    "theme": {
                        "highlight_fg": "default",
                        "highlight_bg": "default",
                        "prefix_color": "cyan",
                    },
                },
                "hosts": [
                    {
                        "type": "host",
                        "name": "demo",
                        "host": "demo.example.com:22",
                        "user": "deploy",
                    }
                ],
            }
        )

        self.assertEqual(errors, [])

    def test_direct_validator_reports_placeholder_and_node_errors(self):
        errors = config_validation.validate_hosts_config(
            {
                "config": {
                    "placeholders": {
                        "site": "example.com",
                    },
                    "relay_temp_dir": "{{missing}}",
                },
                "hosts": [
                    {
                        "type": "host",
                        "name": "bad",
                        "host": "host.{{site}}:70000",
                        "user": "{{missing_user}}",
                        "password": "pw",
                        "unknown": True,
                    }
                ],
            }
        )
        joined = "\n".join(errors)

        self.assertIn("Unknown placeholder", joined)
        self.assertIn("Port '70000'", joined)
        self.assertIn("Unknown field", joined)

    def test_default_config_does_not_share_placeholders(self):
        first = config_validation.default_config()
        second = config_validation.default_config()
        first["placeholders"]["site"] = "example.com"

        self.assertNotIn("site", second["placeholders"])


if __name__ == "__main__":
    unittest.main()
