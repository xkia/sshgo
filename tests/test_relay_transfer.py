import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO

import host_manager as host_manager_module
from host_manager import HostManager


class RelayTransferTests(unittest.TestCase):
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

    def test_relay_scp_specs_bracket_ipv6_hosts(self):
        base_cmd = [
            "./relay_transfer.exp",
            "-h",
            "2001:db8::5",
            "-u",
            "targetuser",
            "-J-host",
            "2001:db8::1",
            "-J-user",
            "jumpuser",
            "-action",
            "download",
            "-local",
            "local.txt",
            "-remote",
            "/tmp/remote.txt",
            "-temp",
            "/tmp/relay.txt",
        ]

        for print_target, expected in (
            ("target-download", "'targetuser@[2001:db8::5]:/tmp/remote.txt'"),
            ("local-to-jump", "'jumpuser@[2001:db8::1]:/tmp/relay.txt'"),
            ("jump-to-local", "'jumpuser@[2001:db8::1]:/tmp/relay.txt'"),
        ):
            with self.subTest(print_target=print_target):
                result = subprocess.run(
                    base_cmd + ["-print-command", print_target],
                    cwd=os.getcwd(),
                    check=True,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

                self.assertIn(expected, result.stdout.strip())

    def test_relay_jump_command_uses_raw_ipv6_for_ssh_target(self):
        with open("relay_transfer.exp", "r", encoding="utf-8") as f:
            script = f.read()

        self.assertIn("set jump_target [target_string $jump_user $jump_host]", script)
        self.assertNotIn(
            "set jump_target [scp_target_string $jump_user $jump_host]\n"
            "    set cmd [list ssh]",
            script,
        )

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


if __name__ == "__main__":
    unittest.main()
