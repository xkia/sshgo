import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO

import host_manager as host_manager_module
from connection_planner import ConnectionPlanner

try:
    from fixtures import jump_with_target, manager_for_config
except ImportError:
    from tests.fixtures import jump_with_target, manager_for_config


class RelayTransferTests(unittest.TestCase):
    def _planner(self, manager):
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return ConnectionPlanner(manager, script_dir)

    def _manager(self, temp_dir):
        return manager_for_config(temp_dir, hosts=[jump_with_target()])

    def _write_fake_tool(self, directory, name, content):
        path = os.path.join(directory, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(path, 0o755)
        return path

    def _write_fake_ssh(self, directory):
        return self._write_fake_tool(
            directory,
            "ssh",
            """#!/bin/sh
printf '\\n__SSHGO_RELAY_COMMAND_START__\\n'
exit 0
""",
        )

    def _write_fake_scp(self, directory):
        return self._write_fake_tool(
            directory,
            "scp",
            """#!/bin/sh
printf '%s\\n' "$*" >> "$SSHGO_FAKE_SCP_LOG"
exit 0
""",
        )

    def _relay_upload_cmd(self, local_path, remote_path="/tmp/remote.txt"):
        return [
            os.path.abspath("relay_transfer.exp"),
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
            local_path,
            "-remote",
            remote_path,
            "-temp",
            "/tmp/relay.txt",
        ]

    def _fake_tool_env(self, tool_dir, scp_log):
        env = os.environ.copy()
        env["PATH"] = tool_dir + os.pathsep + env.get("PATH", "")
        env["SSHGO_FAKE_SCP_LOG"] = scp_log
        return env

    def _run_relay_upload_with_fake_target_scp(
        self, temp_dir, target_output, target_exit
    ):
        local_path = os.path.join(temp_dir, "local.txt")
        scp_log = os.path.join(temp_dir, "scp.log")
        with open(local_path, "w", encoding="utf-8") as f:
            f.write("payload")

        self._write_fake_tool(
            temp_dir,
            "ssh",
            """#!/bin/sh
printf '\\n__SSHGO_RELAY_COMMAND_START__\\n'
case "$*" in
  *scp*)
    printf '%s' "$SSHGO_FAKE_TARGET_SCP_OUTPUT"
    exit "$SSHGO_FAKE_TARGET_SCP_EXIT"
    ;;
esac
exit 0
""",
        )
        self._write_fake_scp(temp_dir)
        self._write_fake_tool(
            temp_dir,
            "sftp",
            """#!/bin/sh
printf 'sftp> '
IFS= read -r line
printf 'Uploading fake\\nsftp> '
IFS= read -r line
exit 0
""",
        )
        env = self._fake_tool_env(temp_dir, scp_log)
        env["SSHGO_JUMPER_PASS"] = "unused-jump-pass"
        env["SSHGO_TARGET_PASS"] = "unused-target-pass"
        env["SSHGO_FAKE_TARGET_SCP_OUTPUT"] = target_output
        env["SSHGO_FAKE_TARGET_SCP_EXIT"] = str(target_exit)

        result = subprocess.run(
            self._relay_upload_cmd(local_path),
            cwd=os.getcwd(),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )
        return result, scp_log

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
            self.assertEqual(args[args.index("-transfer-timeout") + 1], "1800")
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

            plan = self._planner(manager).build_relay_command_plan(
                target, "download", "/remote/file.txt", "local-file.txt"
            )
            args = plan.args

        self.assertEqual(args[args.index("-action") + 1], "download")
        self.assertEqual(args[args.index("-local") + 1], "local-file.txt")
        self.assertEqual(args[args.index("-remote") + 1], "/remote/file.txt")

    def test_relay_transfer_timeout_can_be_configured(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            manager.config["relay_transfer_timeout"] = 42
            target = manager.find_host_by_alias("target")
            target["transfer_jump_mode"] = "relay"

            plan = self._planner(manager).build_relay_command_plan(
                target, "upload", "local.txt", "/remote/file.txt"
            )
            args = plan.args

        self.assertEqual(args[args.index("-transfer-timeout") + 1], "42")

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

    def test_relay_transfer_consumes_option_shaped_path_value(self):
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
            "-h",
            "-remote",
            "/tmp/remote.txt",
            "-temp",
            "/tmp/relay.txt",
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

        self.assertIn("'-h'", result.stdout)
        self.assertIn("'jumpuser@jump.example.com:/tmp/relay.txt'", result.stdout)

    def test_relay_transfer_reports_cleanup_warning_without_masking_failure(self):
        with open("relay_transfer.exp", "r", encoding="utf-8") as f:
            script = f.read()

        self.assertIn("proc wait_exit_status", script)
        self.assertIn("Warning: unexpected process wait result", script)
        self.assertIn("proc run_local_staging_transfer", script)
        self.assertIn("SFTP staging failed; retrying with relay scp protocols", script)
        self.assertIn("proc should_retry_default_scp", script)
        self.assertIn("Warning: could not remove relay temp file", script)
        self.assertIn(
            "Legacy scp failed; retrying with OpenSSH default scp protocol",
            script,
        )
        self.assertIn("cleanup_temp_path $temp_path", script)
        self.assertIn("Relay upload failed while copying to jump host", script)
        self.assertIn("fail \"\\nRelay upload failed.\\n\" 1", script)
        self.assertIn("fail \"\\nRelay download failed.\\n\" 1", script)

    def test_relay_jump_command_uses_process_exit_status_without_marker_output(self):
        with open("relay_transfer.exp", "r", encoding="utf-8") as f:
            script = f.read()

        self.assertIn("__SSHGO_RELAY_COMMAND_START__", script)
        self.assertIn("set exit_status [wait_exit_status $jump_spawn_id]", script)
        self.assertNotIn('send -i $expect_out(spawn_id) "stty -echo', script)
        self.assertNotIn("__sshgo_status", script)
        self.assertNotIn("stty echo; exit", script)
        self.assertNotIn("__SSHGO_RELAY_STATUS__", script)

    def test_relay_transfer_uses_separate_command_and_transfer_timeouts(self):
        with open("relay_transfer.exp", "r", encoding="utf-8") as f:
            script = f.read()

        self.assertIn("set command_timeout 30", script)
        self.assertIn("set transfer_timeout 1800", script)
        self.assertIn('"-transfer-timeout" { set transfer_timeout $value }', script)
        self.assertIn("proc effective_transfer_timeout", script)
        self.assertIn("return -1", script)
        self.assertIn("set timeout $command_timeout", script)
        self.assertIn("set timeout [effective_transfer_timeout]", script)
        self.assertIn("Relay command timed out", script)
        self.assertIn("Relay transfer timed out while $context after", script)
        self.assertNotIn("expect_auth_until_eof_with_timeout_message", script)

    def test_relay_transfer_prefers_legacy_scp_and_prints_phases(self):
        with open("relay_transfer.exp", "r", encoding="utf-8") as f:
            script = f.read()

        self.assertIn("proc relay_phase", script)
        self.assertIn("using SFTP staging", script)
        self.assertIn("using legacy SCP protocol", script)
        self.assertIn("using OpenSSH default scp protocol", script)
        self.assertIn("proc run_local_sftp_transfer", script)
        self.assertIn("proc build_local_sftp_to_jump", script)
        self.assertIn("set exit_status [wait_exit_status $sid]", script)
        self.assertIn("return $exit_status", script)
        self.assertIn("proc sftp_staging_paths_are_safe", script)
        self.assertIn("Relay scp protocol option is unavailable", script)
        self.assertIn("set retryable_protocol_error 0", script)
        self.assertIn("proc status_retry_protocol", script)
        self.assertIn("proc is_retry_protocol_status", script)
        self.assertIn("proc run_local_scp_with_protocol_fallback", script)
        self.assertIn("proc run_jump_scp_with_protocol_fallback", script)
        self.assertIn("[sftp_put_command $local_path $temp_path]", script)
        self.assertIn("[sftp_get_command $temp_path $local_path]", script)
        self.assertIn("[build_local_scp_to_jump $local_path $temp_path 1]", script)
        self.assertIn("[target_scp_command $temp_path $remote_spec 1]", script)
        self.assertIn("close_spawn", script)

    def test_relay_transfer_rejects_invalid_transfer_timeout(self):
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
            "-transfer-timeout",
            "-1",
            "-print-command",
            "local-to-jump",
        ]
        result = subprocess.run(
            cmd,
            cwd=os.getcwd(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("Invalid relay transfer timeout", result.stdout + result.stderr)

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

    def test_relay_target_scp_legacy_print_command_uses_dash_o(self):
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
            "target-upload-legacy",
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
        self.assertIn("'targetuser@target.example.com:/tmp/remote.txt'", rendered)

    def test_relay_local_staging_sftp_print_command_shows_sftp_and_put(self):
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
            "local file.txt",
            "-remote",
            "/tmp/remote.txt",
            "-temp",
            "/tmp/relay file.txt",
            "-print-command",
            "local-staging-sftp",
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
        self.assertIn("'sftp'", rendered)
        self.assertIn("'BatchMode=no'", rendered)
        self.assertIn("put 'local file.txt' '/tmp/relay file.txt'", rendered)

    def test_relay_sftp_staging_success_does_not_use_local_scp_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_path = os.path.join(temp_dir, "local.txt")
            scp_log = os.path.join(temp_dir, "scp.log")
            with open(local_path, "w", encoding="utf-8") as f:
                f.write("payload")

            self._write_fake_ssh(temp_dir)
            self._write_fake_scp(temp_dir)
            self._write_fake_tool(
                temp_dir,
                "sftp",
                """#!/bin/sh
printf 'sftp> '
IFS= read -r line
printf 'Uploading fake\\nsftp> '
IFS= read -r line
exit 0
""",
            )

            result = subprocess.run(
                self._relay_upload_cmd(local_path),
                cwd=os.getcwd(),
                env=self._fake_tool_env(temp_dir, scp_log),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("Relay upload complete", output)
        self.assertNotIn("mkdir -p", output)
        self.assertNotIn("__sshgo_status", output)
        self.assertNotIn("stty echo", output)
        self.assertNotIn("exit $__sshgo_status", output)
        self.assertFalse(os.path.exists(scp_log))

    def test_relay_auto_password_prompts_are_hidden(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_path = os.path.join(temp_dir, "local.txt")
            scp_log = os.path.join(temp_dir, "scp.log")
            jump_pass_log = os.path.join(temp_dir, "jump-pass.log")
            target_pass_log = os.path.join(temp_dir, "target-pass.log")
            with open(local_path, "w", encoding="utf-8") as f:
                f.write("payload")

            self._write_fake_tool(
                temp_dir,
                "ssh",
                """#!/bin/sh
printf 'jump password: '
IFS= read -r pass
printf '%s\\n' "$pass" >> "$SSHGO_FAKE_JUMP_PASS_LOG"
printf '\\n__SSHGO_RELAY_COMMAND_START__\\n'
case "$*" in
  *scp*)
    printf 'target password: '
    IFS= read -r pass
    printf '%s\\n' "$pass" >> "$SSHGO_FAKE_TARGET_PASS_LOG"
    ;;
esac
exit 0
""",
            )
            self._write_fake_scp(temp_dir)
            self._write_fake_tool(
                temp_dir,
                "sftp",
                """#!/bin/sh
printf 'jump password: '
IFS= read -r pass
printf '%s\\n' "$pass" >> "$SSHGO_FAKE_JUMP_PASS_LOG"
printf 'sftp> '
IFS= read -r line
printf 'Uploading fake\\nsftp> '
IFS= read -r line
exit 0
""",
            )
            env = self._fake_tool_env(temp_dir, scp_log)
            env["SSHGO_JUMPER_PASS"] = "jump-pass"
            env["SSHGO_TARGET_PASS"] = "target-pass"
            env["SSHGO_FAKE_JUMP_PASS_LOG"] = jump_pass_log
            env["SSHGO_FAKE_TARGET_PASS_LOG"] = target_pass_log

            result = subprocess.run(
                self._relay_upload_cmd(local_path),
                cwd=os.getcwd(),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

            with open(jump_pass_log, "r", encoding="utf-8") as f:
                sent_jump_passwords = f.read().splitlines()
            with open(target_pass_log, "r", encoding="utf-8") as f:
                sent_target_passwords = f.read().splitlines()

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("password:", output)
        self.assertIn("Relay upload complete", output)
        self.assertNotIn("mkdir -p", output)
        self.assertNotIn("__SSHGO_RELAY_COMMAND_START__", output)
        self.assertGreaterEqual(len(sent_jump_passwords), 1)
        self.assertTrue(all(password == "jump-pass" for password in sent_jump_passwords))
        self.assertGreaterEqual(len(sent_target_passwords), 1)
        self.assertTrue(all(password == "target-pass" for password in sent_target_passwords))
        self.assertFalse(os.path.exists(scp_log))

    def test_relay_target_scp_output_shows_with_auto_auth_but_no_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result, scp_log = self._run_relay_upload_with_fake_target_scp(
                temp_dir, "REMOTE_SCP_PROGRESS 100%\r\n", 0
            )

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("REMOTE_SCP_PROGRESS 100%", output)
        self.assertNotIn("password:", output)
        self.assertIn("Relay upload complete", output)
        self.assertFalse(os.path.exists(scp_log))

    def test_relay_target_scp_final_output_without_newline_shows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result, scp_log = self._run_relay_upload_with_fake_target_scp(
                temp_dir, "REMOTE_SCP_DONE", 0
            )

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("REMOTE_SCP_DONE", output)
        self.assertNotIn("password:", output)
        self.assertIn("Relay upload complete", output)
        self.assertFalse(os.path.exists(scp_log))

    def test_relay_target_scp_no_such_file_error_shows_with_hidden_auto_auth(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result, scp_log = self._run_relay_upload_with_fake_target_scp(
                temp_dir,
                "scp: /tmp/remote.txt: No such file or directory\r\n",
                1,
            )

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("scp: /tmp/remote.txt: No such file or directory", output)
        self.assertNotIn("password:", output)
        self.assertIn("Relay upload failed", output)
        self.assertFalse(os.path.exists(scp_log))

    def test_relay_target_scp_permission_error_shows_with_hidden_auto_auth(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result, scp_log = self._run_relay_upload_with_fake_target_scp(
                temp_dir,
                "scp: /tmp/remote.txt: Permission denied\r\n",
                1,
            )

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("scp: /tmp/remote.txt: Permission denied", output)
        self.assertNotIn("password:", output)
        self.assertIn("Relay upload failed", output)
        self.assertFalse(os.path.exists(scp_log))

    def test_relay_sftp_staging_command_failure_does_not_fallback_to_scp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_path = os.path.join(temp_dir, "local.txt")
            scp_log = os.path.join(temp_dir, "scp.log")
            with open(local_path, "w", encoding="utf-8") as f:
                f.write("payload")

            self._write_fake_ssh(temp_dir)
            self._write_fake_scp(temp_dir)
            self._write_fake_tool(
                temp_dir,
                "sftp",
                """#!/bin/sh
printf 'sftp> '
IFS= read -r line
printf "Couldn't write remote file\\nsftp> "
IFS= read -r line
exit 0
""",
            )

            result = subprocess.run(
                self._relay_upload_cmd(local_path),
                cwd=os.getcwd(),
                env=self._fake_tool_env(temp_dir, scp_log),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("Relay upload failed while copying to jump host", output)
        self.assertNotIn("using legacy SCP protocol", output)
        self.assertFalse(os.path.exists(scp_log))

    def test_relay_sftp_staging_dest_open_failure_does_not_report_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_path = os.path.join(temp_dir, "local.txt")
            scp_log = os.path.join(temp_dir, "scp.log")
            with open(local_path, "w", encoding="utf-8") as f:
                f.write("payload")

            self._write_fake_ssh(temp_dir)
            self._write_fake_scp(temp_dir)
            self._write_fake_tool(
                temp_dir,
                "sftp",
                """#!/bin/sh
printf 'sftp> '
IFS= read -r line
printf 'dest open "/tmp/relay.txt": No such file or directory\\nsftp> '
IFS= read -r line
exit 0
""",
            )

            result = subprocess.run(
                self._relay_upload_cmd(local_path),
                cwd=os.getcwd(),
                env=self._fake_tool_env(temp_dir, scp_log),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("Relay staging transfer failed", output)
        self.assertIn("Relay upload failed while copying to jump host", output)
        self.assertNotIn("Relay upload complete", output)
        self.assertFalse(os.path.exists(scp_log))

    def test_relay_sftp_staging_subsystem_failure_falls_back_to_scp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_path = os.path.join(temp_dir, "local.txt")
            scp_log = os.path.join(temp_dir, "scp.log")
            with open(local_path, "w", encoding="utf-8") as f:
                f.write("payload")

            self._write_fake_ssh(temp_dir)
            self._write_fake_scp(temp_dir)
            self._write_fake_tool(
                temp_dir,
                "sftp",
                """#!/bin/sh
printf 'subsystem request failed\\n'
exit 1
""",
            )

            result = subprocess.run(
                self._relay_upload_cmd(local_path),
                cwd=os.getcwd(),
                env=self._fake_tool_env(temp_dir, scp_log),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

            with open(scp_log, "r", encoding="utf-8") as f:
                scp_output = f.read()

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("SFTP staging failed; retrying with relay scp protocols", output)
        self.assertIn("-O", scp_output)

    def test_relay_sftp_staging_is_skipped_for_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_path = os.path.join(temp_dir, "bad\nname.txt")
            sftp_log = os.path.join(temp_dir, "sftp.log")
            scp_log = os.path.join(temp_dir, "scp.log")
            with open(local_path, "w", encoding="utf-8") as f:
                f.write("payload")

            self._write_fake_ssh(temp_dir)
            self._write_fake_scp(temp_dir)
            self._write_fake_tool(
                temp_dir,
                "sftp",
                """#!/bin/sh
printf 'called\\n' >> "$SSHGO_FAKE_SFTP_LOG"
exit 1
""",
            )
            env = self._fake_tool_env(temp_dir, scp_log)
            env["SSHGO_FAKE_SFTP_LOG"] = sftp_log

            result = subprocess.run(
                self._relay_upload_cmd(local_path),
                cwd=os.getcwd(),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

            with open(scp_log, "r", encoding="utf-8") as f:
                scp_output = f.read()

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("SFTP staging skipped for unsafe path characters", output)
        self.assertFalse(os.path.exists(sftp_log))
        self.assertIn("-O", scp_output)

    def test_relay_sftp_staging_is_skipped_for_relative_leading_dash_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_path = "-bad.txt"
            sftp_log = os.path.join(temp_dir, "sftp.log")
            scp_log = os.path.join(temp_dir, "scp.log")
            with open(os.path.join(temp_dir, local_path), "w", encoding="utf-8") as f:
                f.write("payload")

            self._write_fake_ssh(temp_dir)
            self._write_fake_scp(temp_dir)
            self._write_fake_tool(
                temp_dir,
                "sftp",
                """#!/bin/sh
printf 'called\\n' >> "$SSHGO_FAKE_SFTP_LOG"
exit 1
""",
            )
            env = self._fake_tool_env(temp_dir, scp_log)
            env["SSHGO_FAKE_SFTP_LOG"] = sftp_log

            result = subprocess.run(
                self._relay_upload_cmd(local_path),
                cwd=temp_dir,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

            with open(scp_log, "r", encoding="utf-8") as f:
                scp_output = f.read()

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("SFTP staging skipped for unsafe path characters", output)
        self.assertFalse(os.path.exists(sftp_log))
        self.assertIn("-O", scp_output)

    def test_relay_local_scp_permission_failure_does_not_retry_default_protocol(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_path = os.path.join(temp_dir, 'bad"name.txt')
            scp_log = os.path.join(temp_dir, "scp.log")
            sftp_log = os.path.join(temp_dir, "sftp.log")
            with open(local_path, "w", encoding="utf-8") as f:
                f.write("payload")

            self._write_fake_ssh(temp_dir)
            self._write_fake_tool(
                temp_dir,
                "scp",
                """#!/bin/sh
printf '%s\\n' "$*" >> "$SSHGO_FAKE_SCP_LOG"
printf 'Permission denied\\n'
exit 1
""",
            )
            self._write_fake_tool(
                temp_dir,
                "sftp",
                """#!/bin/sh
printf 'called\\n' >> "$SSHGO_FAKE_SFTP_LOG"
exit 1
""",
            )
            env = self._fake_tool_env(temp_dir, scp_log)
            env["SSHGO_FAKE_SFTP_LOG"] = sftp_log

            result = subprocess.run(
                self._relay_upload_cmd(local_path),
                cwd=os.getcwd(),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

            with open(scp_log, "r", encoding="utf-8") as f:
                scp_lines = f.read().splitlines()

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("Relay upload failed while copying to jump host", output)
        self.assertIn("Authentication failed", output)
        self.assertNotIn("using OpenSSH default scp protocol", output)
        self.assertEqual(len(scp_lines), 1)
        self.assertIn("-O", scp_lines[0])
        self.assertFalse(os.path.exists(sftp_log))

    def test_relay_local_scp_protocol_failure_retries_default_protocol(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_path = os.path.join(temp_dir, 'bad"name.txt')
            scp_log = os.path.join(temp_dir, "scp.log")
            sftp_log = os.path.join(temp_dir, "sftp.log")
            with open(local_path, "w", encoding="utf-8") as f:
                f.write("payload")

            self._write_fake_ssh(temp_dir)
            self._write_fake_tool(
                temp_dir,
                "scp",
                """#!/bin/sh
printf '%s\\n' "$*" >> "$SSHGO_FAKE_SCP_LOG"
case " $* " in
    *" -O "*) printf 'scp: illegal option -- O\\nusage: scp\\n'; exit 1 ;;
esac
exit 0
""",
            )
            self._write_fake_tool(
                temp_dir,
                "sftp",
                """#!/bin/sh
printf 'called\\n' >> "$SSHGO_FAKE_SFTP_LOG"
exit 1
""",
            )
            env = self._fake_tool_env(temp_dir, scp_log)
            env["SSHGO_FAKE_SFTP_LOG"] = sftp_log

            result = subprocess.run(
                self._relay_upload_cmd(local_path),
                cwd=os.getcwd(),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

            with open(scp_log, "r", encoding="utf-8") as f:
                scp_lines = f.read().splitlines()

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("Relay scp protocol option is unavailable", output)
        self.assertIn("using OpenSSH default scp protocol", output)
        self.assertEqual(len(scp_lines), 2)
        self.assertIn("-O", scp_lines[0])
        self.assertNotIn("-O", scp_lines[1])
        self.assertFalse(os.path.exists(sftp_log))

    def test_relay_local_scp_generic_usage_failure_does_not_retry_default_protocol(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_path = os.path.join(temp_dir, 'bad"name.txt')
            scp_log = os.path.join(temp_dir, "scp.log")
            sftp_log = os.path.join(temp_dir, "sftp.log")
            with open(local_path, "w", encoding="utf-8") as f:
                f.write("payload")

            self._write_fake_ssh(temp_dir)
            self._write_fake_tool(
                temp_dir,
                "scp",
                """#!/bin/sh
printf '%s\\n' "$*" >> "$SSHGO_FAKE_SCP_LOG"
printf 'usage: scp\\n'
exit 1
""",
            )
            self._write_fake_tool(
                temp_dir,
                "sftp",
                """#!/bin/sh
printf 'called\\n' >> "$SSHGO_FAKE_SFTP_LOG"
exit 1
""",
            )
            env = self._fake_tool_env(temp_dir, scp_log)
            env["SSHGO_FAKE_SFTP_LOG"] = sftp_log

            result = subprocess.run(
                self._relay_upload_cmd(local_path),
                cwd=os.getcwd(),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

            with open(scp_log, "r", encoding="utf-8") as f:
                scp_lines = f.read().splitlines()

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("Relay upload failed while copying to jump host", output)
        self.assertNotIn("using OpenSSH default scp protocol", output)
        self.assertEqual(len(scp_lines), 1)
        self.assertIn("-O", scp_lines[0])
        self.assertFalse(os.path.exists(sftp_log))

    def test_relay_jump_scp_protocol_failure_retries_default_protocol(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_path = os.path.join(temp_dir, "local.txt")
            scp_log = os.path.join(temp_dir, "scp.log")
            with open(local_path, "w", encoding="utf-8") as f:
                f.write("payload")

            self._write_fake_tool(
                temp_dir,
                "ssh",
                """#!/bin/sh
printf '\\n__SSHGO_RELAY_COMMAND_START__\\n'
case " $* " in
    *"'-O'"*)
        printf 'scp: illegal option -- O\\nusage: scp\\n'
        exit 1
        ;;
esac
exit 0
""",
            )
            self._write_fake_scp(temp_dir)
            self._write_fake_tool(
                temp_dir,
                "sftp",
                """#!/bin/sh
printf 'sftp> '
IFS= read -r line
printf 'Uploading fake\\nsftp> '
IFS= read -r line
exit 0
""",
            )

            result = subprocess.run(
                self._relay_upload_cmd(local_path),
                cwd=os.getcwd(),
                env=self._fake_tool_env(temp_dir, scp_log),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn(
            "copying from jump host to target host using OpenSSH default scp protocol",
            output,
        )
        self.assertFalse(os.path.exists(scp_log))

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
