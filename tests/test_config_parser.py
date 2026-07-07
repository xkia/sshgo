import os
import tempfile
import unittest

from config_parser import SshConfigParser


class SshConfigParserTests(unittest.TestCase):
    def test_fallback_parser_handles_quoted_identity_file_and_ipv6(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home_dir = os.path.join(temp_dir, "home")
            ssh_dir = os.path.join(home_dir, ".ssh")
            os.makedirs(ssh_dir)
            config_path = os.path.join(ssh_dir, "config")
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(
                    """
Host *
    User default-user

Host prod
    HostName 2001:db8::5
    Port 2222
    IdentityFile "~/Keys/prod key"
"""
                )

            old_home = os.environ.get("HOME")
            os.environ["HOME"] = home_dir
            parser = SshConfigParser()
            parser._ssh_g_config = lambda alias: None
            try:
                hosts = parser.parse()
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0]["name"], "prod (~/.ssh/config)")
        self.assertEqual(hosts[0]["host"], "2001:db8::5")
        self.assertEqual(hosts[0]["port"], "2222")
        self.assertEqual(hosts[0]["user"], "default-user")
        self.assertEqual(
            hosts[0]["id_file"],
            os.path.join(home_dir, "Keys", "prod key"),
        )

    def test_ssh_g_result_is_preferred_over_fallback_params(self):
        parser = SshConfigParser()
        parser._ssh_g_config = lambda alias: {
            "hostname": "2001:db8::6",
            "port": "2200",
            "user": "deploy",
            "identityfile": ["~/keys/id_ed25519", "~/.ssh/id_rsa"],
        }

        host = parser._finalize_host_from_ssh(
            "prod",
            {"identityfile": "~/keys/id_ed25519"},
        )

        self.assertEqual(host["host"], "2001:db8::6")
        self.assertEqual(host["port"], "2200")
        self.assertEqual(host["user"], "deploy")
        self.assertTrue(host["id_file"].endswith("/keys/id_ed25519"))

    def test_ssh_g_default_identity_files_are_not_imported_as_explicit_keys(self):
        parser = SshConfigParser()
        parser._ssh_g_config = lambda alias: {
            "hostname": "example.com",
            "port": "22",
            "user": "deploy",
            "identityfile": ["~/.ssh/id_rsa", "~/.ssh/id_ed25519"],
        }

        host = parser._finalize_host_from_ssh("prod", {})

        self.assertEqual(host["id_file"], "")

    def test_parser_discovers_hosts_from_included_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home_dir = os.path.join(temp_dir, "home")
            ssh_dir = os.path.join(home_dir, ".ssh")
            include_dir = os.path.join(ssh_dir, "conf.d")
            os.makedirs(include_dir)
            with open(os.path.join(ssh_dir, "config"), "w", encoding="utf-8") as f:
                f.write("Include conf.d/*.conf\n")
            with open(
                os.path.join(include_dir, "prod.conf"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(
                    """
Host included-prod
    HostName included.example.com
    User deploy
"""
                )

            old_home = os.environ.get("HOME")
            os.environ["HOME"] = home_dir
            parser = SshConfigParser()
            parser._ssh_g_config = lambda alias: None
            try:
                hosts = parser.parse()
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

        self.assertEqual(
            [host["name"] for host in hosts],
            ["included-prod (~/.ssh/config)"],
        )
        self.assertEqual(hosts[0]["host"], "included.example.com")
        self.assertNotIn("port", hosts[0])

    def test_parser_ignores_inline_comments_on_host_and_include_lines(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home_dir = os.path.join(temp_dir, "home")
            ssh_dir = os.path.join(home_dir, ".ssh")
            include_dir = os.path.join(ssh_dir, "conf.d")
            os.makedirs(include_dir)
            with open(os.path.join(ssh_dir, "config"), "w", encoding="utf-8") as f:
                f.write("Include conf.d/*.conf # include local hosts\n")
            with open(
                os.path.join(include_dir, "prod.conf"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(
                    """
Host prod # production host
    HostName prod.example.com
    User deploy
"""
                )

            old_home = os.environ.get("HOME")
            os.environ["HOME"] = home_dir
            parser = SshConfigParser()
            parser._ssh_g_config = lambda alias: None
            try:
                hosts = parser.parse()
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

        self.assertEqual(
            [host["name"] for host in hosts],
            ["prod (~/.ssh/config)"],
        )
        self.assertEqual(hosts[0]["host"], "prod.example.com")
        self.assertNotIn("port", hosts[0])

    def test_nested_include_paths_are_relative_to_ssh_config_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home_dir = os.path.join(temp_dir, "home")
            ssh_dir = os.path.join(home_dir, ".ssh")
            include_dir = os.path.join(ssh_dir, "conf.d")
            os.makedirs(include_dir)
            with open(os.path.join(ssh_dir, "config"), "w", encoding="utf-8") as f:
                f.write("Include conf.d/one.conf\n")
            with open(
                os.path.join(include_dir, "one.conf"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write("Include two.conf\n")
            with open(os.path.join(ssh_dir, "two.conf"), "w", encoding="utf-8") as f:
                f.write(
                    """
Host root-relative
    HostName root.example.com
"""
                )
            with open(
                os.path.join(include_dir, "two.conf"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(
                    """
Host dir-relative
    HostName dir.example.com
"""
                )

            old_home = os.environ.get("HOME")
            os.environ["HOME"] = home_dir
            parser = SshConfigParser()
            parser._ssh_g_config = lambda alias: None
            try:
                hosts = parser.parse()
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

        self.assertEqual(
            [host["name"] for host in hosts],
            ["root-relative (~/.ssh/config)"],
        )

    def test_fallback_parser_inlines_include_inside_host_block(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home_dir = os.path.join(temp_dir, "home")
            ssh_dir = os.path.join(home_dir, ".ssh")
            os.makedirs(ssh_dir)
            with open(os.path.join(ssh_dir, "config"), "w", encoding="utf-8") as f:
                f.write(
                    """
Host prod
    HostName before.example.com
    Include prod-extra.conf
    User deploy
"""
                )
            with open(
                os.path.join(ssh_dir, "prod-extra.conf"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(
                    """
Port 2200
IdentityFile "~/Keys/prod key"
"""
                )

            old_home = os.environ.get("HOME")
            os.environ["HOME"] = home_dir
            parser = SshConfigParser()
            parser._ssh_g_config = lambda alias: None
            try:
                hosts = parser.parse()
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0]["host"], "before.example.com")
        self.assertEqual(hosts[0]["port"], "2200")
        self.assertEqual(hosts[0]["user"], "deploy")
        self.assertEqual(
            hosts[0]["id_file"],
            os.path.join(home_dir, "Keys", "prod key"),
        )

    def test_match_exec_skips_ssh_g_import_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home_dir = os.path.join(temp_dir, "home")
            ssh_dir = os.path.join(home_dir, ".ssh")
            os.makedirs(ssh_dir)
            with open(os.path.join(ssh_dir, "config"), "w", encoding="utf-8") as f:
                f.write(
                    """
Host prod
    HostName prod.example.com
    User deploy

Match exec "echo should-not-run"
    User matched
"""
                )

            old_home = os.environ.get("HOME")
            os.environ["HOME"] = home_dir
            parser = SshConfigParser()
            parser._ssh_g_config = lambda alias: self.fail(
                "ssh -G should not run when Match exec is present"
            )
            try:
                hosts = parser.parse()
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

        self.assertEqual(hosts[0]["name"], "prod (~/.ssh/config)")
        self.assertEqual(hosts[0]["user"], "deploy")


if __name__ == "__main__":
    unittest.main()
