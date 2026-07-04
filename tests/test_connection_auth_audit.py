import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO

import host_manager as host_manager_module
from host_manager import HostManager


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
        self.assertIn("set custom_proxy_command \"\"", script)
        self.assertIn("set jumper_proxy_command \"\"", script)
        self.assertIn("set tunnel_proxy_command \"\"", script)
        self.assertIn("\"-proxy-command\" { set custom_proxy_command $value }", script)
        self.assertIn("\"-j-proxy-command\" { set jumper_proxy_command $value }", script)
        self.assertIn("\"-tunnel-proxy-command\" { set tunnel_proxy_command $value }", script)
        self.assertIn("\"-print-command\" { set print_command $value }", script)
        self.assertIn("ProxyCommand=$custom_proxy_command", script)

    def test_sftp_exp_supports_custom_proxy_command(self):
        with open("sftp_login.exp", "r", encoding="utf-8") as f:
            script = f.read()

        self.assertIn("set custom_proxy_command \"\"", script)
        self.assertIn("set tunnel_proxy_command \"\"", script)
        self.assertIn("\"-proxy-command\" { set custom_proxy_command $value }", script)
        self.assertIn("\"-tunnel-proxy-command\" { set tunnel_proxy_command $value }", script)
        self.assertIn("\"-print-command\" { set print_command $value }", script)
        self.assertIn("ProxyCommand=$custom_proxy_command", script)
        self.assertNotIn("jumper_id_file", script)
        self.assertNotIn("\"-j-i\"", script)

    def test_describe_host_uses_resolved_connection_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")

            details = dict(manager.describe_host(target))

            self.assertEqual(details["Target"], "targetuser@target.internal:2222")
            self.assertEqual(details["Auth"], "key")
            self.assertEqual(details["MFA/OTP"], "enabled")
            self.assertEqual(details["SSH Mode"], "shell")
            self.assertEqual(details["Transfer"], "tunnel")
            self.assertEqual(details["Jump Alias"], "jump")
            self.assertEqual(details["Jump Host"], "jump.example.com:2200")
            self.assertEqual(details["Key"], "target_key")
            joined = "\n".join(f"{key}: {value}" for key, value in details.items())
            self.assertNotIn("target-pass", joined)
            self.assertNotIn("jump-pass", joined)
            self.assertNotIn("JBSWY3DPEHPK3PXP", joined)

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
            tunnel_proxy = args[args.index("-tunnel-proxy-command") + 1]
            self.assertIn("-W %h:%p", tunnel_proxy)
            self.assertIn("jumpuser@jump.example.com:2200", tunnel_proxy)

    def test_proxy_command_and_placeholders_are_passed_to_login_exp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "config": {
                    "import_ssh_config": False,
                    "placeholders": {
                        "site_domain": "example.net",
                        "default_user": "root",
                        "key_path": "/tmp/demo key",
                        "local_socks": "127.0.0.1:1080",
                    },
                },
                "hosts": [
                    {
                        "type": "host",
                        "name": "demo-host",
                        "host": "ssh.{{site_domain}}:2222",
                        "user": "{{default_user}}",
                        "id_file": "{{key_path}}",
                        "proxy_command": "nc -X 5 -x {{local_socks}} %h %p",
                    }
                ],
            }
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)
            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))
            node = manager.find_host_by_alias("demo-host")

            preview_args = manager.build_ssh_command_args(node)
            self.assertEqual(preview_args[preview_args.index("-p") + 1], "2222")
            self.assertEqual(preview_args[preview_args.index("-i") + 1], "/tmp/demo key")
            self.assertEqual(
                preview_args[preview_args.index("-o") + 1],
                "ProxyCommand=nc -X 5 -x 127.0.0.1:1080 %h %p",
            )
            self.assertEqual(preview_args[-1], "root@ssh.example.net")

            captured = {}
            real_execve = host_manager_module.os.execve

            def fake_execve(path, args, env):
                captured["args"] = args
                raise OSError(5, "fake")

            host_manager_module.os.execve = fake_execve
            try:
                with redirect_stderr(StringIO()):
                    with self.assertRaises(SystemExit):
                        manager.execute_interactive_connection(node)
            finally:
                host_manager_module.os.execve = real_execve

            args = captured["args"]
            self.assertEqual(args[args.index("-h") + 1], "ssh.example.net")
            self.assertEqual(args[args.index("-u") + 1], "root")
            self.assertEqual(args[args.index("-p") + 1], "2222")
            self.assertEqual(args[args.index("-i") + 1], "/tmp/demo key")
            self.assertEqual(
                args[args.index("-proxy-command") + 1],
                "nc -X 5 -x 127.0.0.1:1080 %h %p",
            )

            with open(manager.audit.history_path, "r", encoding="utf-8") as f:
                records = [json.loads(line) for line in f if line.strip()]
            started = next(r for r in records if r["result"] == "started")
            self.assertEqual(started["host"], "ssh.example.net")
            self.assertEqual(started["user"], "root")
            self.assertEqual(started["port"], "2222")

    def test_parent_proxy_command_is_used_for_nested_login(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "config": {
                    "import_ssh_config": False,
                    "placeholders": {"proxy": "127.0.0.1:1080"},
                },
                "hosts": [
                    {
                        "type": "host",
                        "name": "jump",
                        "host": "jump.example.com:2200",
                        "user": "jumpuser",
                        "password": "jump-pass",
                        "proxy_command": "nc -X 5 -x {{proxy}} %h %p",
                        "children": [
                            {
                                "type": "host",
                                "name": "target",
                                "host": "target.internal:22",
                                "user": "targetuser",
                                "password": "target-pass",
                            }
                        ],
                    }
                ],
            }
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)
            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))
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

            args = captured["args"]
            self.assertEqual(args[args.index("-J") + 1], "jumpuser@jump.example.com:2200")
            self.assertEqual(args[args.index("-jump-mode") + 1], "shell")
            self.assertEqual(
                args[args.index("-j-proxy-command") + 1],
                "nc -X 5 -x 127.0.0.1:1080 %h %p",
            )
            self.assertNotIn("-proxy-command", args)

    def test_parent_proxy_command_is_used_for_nested_tunnel_login_exec(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "config": {
                    "import_ssh_config": False,
                    "placeholders": {"proxy": "127.0.0.1:1080"},
                },
                "hosts": [
                    {
                        "type": "host",
                        "name": "jump",
                        "host": "jump.example.com:2200",
                        "user": "jumpuser",
                        "password": "jump-pass",
                        "proxy_command": "nc -X 5 -x {{proxy}} %h %p",
                        "children": [
                            {
                                "type": "host",
                                "name": "target",
                                "host": "target.internal:2222",
                                "user": "targetuser",
                                "password": "target-pass",
                                "ssh_jump_mode": "tunnel",
                            }
                        ],
                    }
                ],
            }
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)
            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))
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

            args = captured["args"]
            self.assertEqual(args[args.index("-jump-mode") + 1], "tunnel")
            tunnel_proxy = args[args.index("-tunnel-proxy-command") + 1]
            self.assertIn("ProxyCommand=nc -X 5 -x 127.0.0.1:1080 %%h %%p", tunnel_proxy)
            self.assertIn("-W %h:%p", tunnel_proxy)
            self.assertIn("jumpuser@jump.example.com:2200", tunnel_proxy)
            self.assertNotIn("-j-proxy-command", args)
            self.assertNotIn("-proxy-command", args)

    def test_parent_proxy_command_is_escaped_in_nested_tunnel_preview(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "config": {
                    "import_ssh_config": False,
                    "placeholders": {"proxy": "127.0.0.1:1080"},
                },
                "hosts": [
                    {
                        "type": "host",
                        "name": "jump",
                        "host": "jump.example.com:2200",
                        "user": "jumpuser",
                        "password": "jump-pass",
                        "proxy_command": "nc -X 5 -x {{proxy}} %h %p",
                        "children": [
                            {
                                "type": "host",
                                "name": "target",
                                "host": "target.internal:2222",
                                "user": "targetuser",
                                "password": "target-pass",
                                "ssh_jump_mode": "tunnel",
                            }
                        ],
                    }
                ],
            }
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)
            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))
            target = manager.find_host_by_alias("target")

            args = manager.build_ssh_command_args(target)

        proxy_option = args[args.index("-o") + 1]
        self.assertIn("ProxyCommand=ssh", proxy_option)
        self.assertIn("%%h %%p", proxy_option)
        self.assertIn("-W %h:%p", proxy_option)

    def test_login_exp_print_command_uses_tunnel_proxy_command(self):
        result = subprocess.run(
            [
                "./login.exp",
                "-h",
                "target.internal",
                "-u",
                "targetuser",
                "-J",
                "jumpuser@jump.example.com:2200",
                "-jump-mode",
                "tunnel",
                "-tunnel-proxy-command",
                "ssh -o ProxyCommand='nc -x 127.0.0.1:1080 %%h %%p' -W %h:%p jumpuser@jump.example.com:2200",
                "-print-command",
                "1",
            ],
            cwd=os.getcwd(),
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        rendered = result.stdout.strip()
        self.assertIn("'ssh'", rendered)
        self.assertIn("'-o'", rendered)
        self.assertIn("ProxyCommand=ssh -o ProxyCommand=", rendered)
        self.assertIn("%%h %%p", rendered)
        self.assertIn("-W %h:%p", rendered)

    def test_sftp_exp_print_command_uses_tunnel_proxy_command(self):
        result = subprocess.run(
            [
                "./sftp_login.exp",
                "-h",
                "target.internal",
                "-u",
                "targetuser",
                "-J",
                "jumpuser@jump.example.com:2200",
                "-action",
                "upload",
                "-local",
                "local.txt",
                "-remote",
                "/tmp/remote.txt",
                "-tunnel-proxy-command",
                "ssh -o ProxyCommand='nc -x 127.0.0.1:1080 %%h %%p' -W %h:%p jumpuser@jump.example.com:2200",
                "-print-command",
                "1",
            ],
            cwd=os.getcwd(),
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        rendered = result.stdout.strip()
        self.assertIn("'sftp'", rendered)
        self.assertIn("'-o'", rendered)
        self.assertIn("ProxyCommand=ssh -o ProxyCommand=", rendered)
        self.assertIn("%%h %%p", rendered)
        self.assertIn("-W %h:%p", rendered)

    def test_nested_sftp_tunnel_does_not_pass_jump_identity_file_arg(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")

            args, secrets = manager._build_sftp_command_parts(
                target, "upload", "local.txt", "/tmp/remote.txt"
            )

        self.assertNotIn("-j-i", args)
        self.assertEqual(args[args.index("-i") + 1], "/tmp/target_key")
        tunnel_proxy = args[args.index("-tunnel-proxy-command") + 1]
        self.assertIn("-i /tmp/jump_key", tunnel_proxy)
        self.assertEqual(secrets["jumper_pass"], "jump-pass")

    def test_sftp_rejects_fragile_paths_before_expect_handoff(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")

            with self.assertRaisesRegex(ValueError, "Invalid local SFTP path"):
                manager.build_file_transfer_launch_command_args(
                    target,
                    "upload",
                    'local"bad.txt',
                    "/tmp/remote.txt",
                )

            target["transfer_jump_mode"] = "relay"
            args = manager.build_file_transfer_launch_command_args(
                target,
                "upload",
                'local"bad.txt',
                "/tmp/remote.txt",
            )
            self.assertTrue(args[0].endswith("relay_transfer.exp"))
            self.assertIn('local"bad.txt', args)

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

    def test_proxy_command_and_placeholders_are_passed_to_sftp_exp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "config": {
                    "import_ssh_config": False,
                    "placeholders": {
                        "host_base": "files.example.com",
                        "user": "deploy",
                        "key": "/tmp/files_key",
                        "proxy": "127.0.0.1:1080",
                    },
                },
                "hosts": [
                    {
                        "type": "host",
                        "name": "files",
                        "host": "{{host_base}}:2201",
                        "user": "{{user}}",
                        "id_file": "{{key}}",
                        "proxy_command": "nc -X 5 -x {{proxy}} %h %p",
                    }
                ],
            }
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)
            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))
            node = manager.find_host_by_alias("files")

            args = manager.build_file_transfer_command_args(
                node, "upload", "local.txt", "/tmp/remote.txt"
            )

        self.assertEqual(args[args.index("-h") + 1], "files.example.com")
        self.assertEqual(args[args.index("-u") + 1], "deploy")
        self.assertEqual(args[args.index("-P") + 1], "2201")
        self.assertEqual(args[args.index("-i") + 1], "/tmp/files_key")
        self.assertEqual(
            args[args.index("-proxy-command") + 1],
            "nc -X 5 -x 127.0.0.1:1080 %h %p",
        )

    def test_parent_proxy_command_is_used_for_nested_sftp_and_relay(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "config": {
                    "import_ssh_config": False,
                    "placeholders": {"proxy": "127.0.0.1:1080"},
                },
                "hosts": [
                    {
                        "type": "host",
                        "name": "jump",
                        "host": "jump.example.com:2200",
                        "user": "jumpuser",
                        "password": "jump-pass",
                        "proxy_command": "nc -X 5 -x {{proxy}} %h %p",
                        "children": [
                            {
                                "type": "host",
                                "name": "target",
                                "host": "target.internal:2222",
                                "user": "targetuser",
                                "password": "target-pass",
                            }
                        ],
                    }
                ],
            }
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)
            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))
            target = manager.find_host_by_alias("target")

            sftp_args = manager.build_file_transfer_command_args(
                target, "upload", "local.txt", "/tmp/remote.txt"
            )
            target["transfer_jump_mode"] = "relay"
            relay_args, _ = manager._build_relay_command_parts(
                target, "upload", "local.txt", "/tmp/remote.txt"
            )

        self.assertEqual(
            sftp_args[sftp_args.index("-tunnel-proxy-command") + 1],
            (
                "ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "
                "-p 2200 -o 'ProxyCommand=nc -X 5 -x 127.0.0.1:1080 %%h %%p' "
                "-W %h:%p jumpuser@jump.example.com:2200"
            ),
        )
        self.assertEqual(
            relay_args[relay_args.index("-j-proxy-command") + 1],
            "nc -X 5 -x 127.0.0.1:1080 %h %p",
        )

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

    def test_relay_temp_dir_resolves_global_placeholders(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            manager.config["placeholders"] = {"relay_dir": "/tmp/sshgo-relay-test"}
            manager.config["relay_temp_dir"] = "{{relay_dir}}"

            temp_path = manager._relay_temp_path("local.txt")

        self.assertTrue(temp_path.startswith("/tmp/sshgo-relay-test/"))
        self.assertIn("local.txt", temp_path)

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

    def test_relay_local_scp_uses_jump_proxy_command(self):
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
            "-j-proxy-command",
            "nc -X 5 -x 127.0.0.1:1080 %h %p",
            "-print-command",
            "local-to-jump",
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
        self.assertIn("'-o'", rendered)
        self.assertIn(
            "'ProxyCommand=nc -X 5 -x 127.0.0.1:1080 %h %p'",
            rendered,
        )

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

    def test_runtime_rejects_unsupported_deep_host_nesting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "config": {"import_ssh_config": False},
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
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)
            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))
            target = manager.find_host_by_alias("target")

            with self.assertRaisesRegex(ValueError, "Unsupported nested host topology"):
                manager.build_interactive_launch_command_args(target)

    def test_runtime_placeholder_errors_are_user_facing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "config": {"import_ssh_config": False, "placeholders": {}},
                "hosts": [
                    {
                        "type": "host",
                        "name": "bad-runtime",
                        "host": "bad.{{missing}}:22",
                        "user": "deploy",
                        "password": "pw",
                    }
                ],
            }
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)
            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))
            node = manager.find_host_by_alias("bad-runtime")

            stderr = StringIO()
            with redirect_stderr(stderr):
                with self.assertRaises(SystemExit):
                    manager.execute_interactive_connection(node)

            self.assertIn("Unknown placeholder: missing", stderr.getvalue())

    def test_runtime_rejects_nested_target_proxy_command(self):
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
            target = manager.find_host_by_alias("target")

            with self.assertRaisesRegex(ValueError, "nested jump host modes"):
                manager.build_ssh_command_args(target)
            with self.assertRaisesRegex(ValueError, "nested jump host modes"):
                manager.build_file_transfer_command_args(
                    target, "upload", "local.txt", "/tmp/remote.txt"
                )
            target["transfer_jump_mode"] = "relay"
            with self.assertRaisesRegex(ValueError, "nested jump host modes"):
                manager._build_relay_command_parts(
                    target, "upload", "local.txt", "/tmp/remote.txt"
                )

            stderr = StringIO()
            with redirect_stderr(stderr):
                with self.assertRaises(SystemExit):
                    manager.execute_interactive_connection(target)

            self.assertIn("nested jump host modes", stderr.getvalue())

if __name__ == "__main__":
    unittest.main()
