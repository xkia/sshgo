import json
import os
import pty
import select
import signal
import subprocess
import tempfile
import time
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

    def test_expect_handoff_env_forces_utf8_locale(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            old_env = {
                key: os.environ.get(key)
                for key in ("LANG", "LC_ALL", "LC_CTYPE")
            }
            os.environ["LANG"] = "C"
            os.environ["LC_ALL"] = "C"
            os.environ["LC_CTYPE"] = "C"
            try:
                env = manager._env_for_secret_values({})
            finally:
                for key, value in old_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

        self.assertIn("UTF", env["LANG"].upper())
        self.assertIn("UTF", env["LC_ALL"].upper())
        self.assertIn("UTF", env["LC_CTYPE"].upper())

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

    def test_expect_scripts_configure_utf8_channels(self):
        for path in ("login.exp", "sftp_login.exp", "relay_transfer.exp"):
            with self.subTest(path=path):
                with open(path, "r", encoding="utf-8") as f:
                    script = f.read()
                self.assertIn("encoding system utf-8", script)
                self.assertIn("configure_utf8_channel stdin", script)
                self.assertIn("configure_utf8_channel $spawn_id", script)

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
        with tempfile.TemporaryDirectory() as temp_dir:
            env = os.environ.copy()
            env["TMPDIR"] = temp_dir
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
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(os.listdir(temp_dir), [])

        rendered = result.stdout.strip()
        self.assertIn("'sftp'", rendered)
        self.assertIn("'-b'", rendered)
        self.assertIn("'<sshgo-generated-batch-file>'", rendered)
        self.assertIn("'-o'", rendered)
        self.assertIn("ProxyCommand=ssh -o ProxyCommand=", rendered)
        self.assertIn("%%h %%p", rendered)
        self.assertIn("-W %h:%p", rendered)
        self.assertIn('# batch: put "local.txt" "/tmp/remote.txt"', rendered)
        self.assertNotIn("SSHGO_", rendered)
        self.assertNotIn("sshgo-sftp-", rendered)

    def test_sftp_exp_print_command_for_interactive_mode_uses_no_batch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env = os.environ.copy()
            env["TMPDIR"] = temp_dir
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
                    "interactive",
                    "-tunnel-proxy-command",
                    "ssh -o ProxyCommand='nc -x 127.0.0.1:1080 %%h %%p' -W %h:%p jumpuser@jump.example.com:2200",
                    "-print-command",
                    "1",
                ],
                cwd=os.getcwd(),
                check=True,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(os.listdir(temp_dir), [])

        rendered = result.stdout.strip()
        self.assertIn("'sftp'", rendered)
        self.assertNotIn("'-b'", rendered)
        self.assertNotIn("'-S'", rendered)
        self.assertNotIn("sftp_ssh_wrapper.py", rendered)
        self.assertNotIn("<sshgo-generated-batch-file>", rendered)
        self.assertNotIn("# batch:", rendered)
        self.assertIn("ProxyCommand=ssh -o ProxyCommand=", rendered)

    def test_sftp_ssh_wrapper_filters_batchmode_yes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_ssh = os.path.join(temp_dir, "ssh")
            args_path = os.path.join(temp_dir, "args.json")
            with open(fake_ssh, "w", encoding="utf-8") as f:
                f.write(
                    """#!/bin/sh
python3 - "$SSHGO_FAKE_SSH_ARGS" "$@" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(sys.argv[2:], f)
PY
exit 0
"""
                )
            os.chmod(fake_ssh, 0o755)
            env = os.environ.copy()
            env["PATH"] = temp_dir + os.pathsep + env.get("PATH", "")
            env["SSHGO_FAKE_SSH_ARGS"] = args_path

            result = subprocess.run(
                [
                    "./sftp_ssh_wrapper.py",
                    "-oForwardX11 no",
                    "-obatchmode yes",
                    "-o",
                    "BatchMode=yes",
                    "-l",
                    "targetuser",
                    "target.internal",
                ],
                cwd=os.getcwd(),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with open(args_path, "r", encoding="utf-8") as f:
                args = json.load(f)
            rendered = " ".join(args).lower()
            self.assertIn("batchmode=no", rendered)
            self.assertNotIn("batchmode yes", rendered)
            self.assertNotIn("batchmode=yes", rendered)
            self.assertIn("-l", args)
            self.assertIn("targetuser", args)

    def test_real_sftp_batch_mode_uses_wrapper_without_batchmode_yes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_ssh = os.path.join(temp_dir, "ssh")
            args_path = os.path.join(temp_dir, "args.json")
            batch_path = os.path.join(temp_dir, "batch")
            with open(batch_path, "w", encoding="utf-8") as f:
                f.write("quit\n")
            with open(fake_ssh, "w", encoding="utf-8") as f:
                f.write(
                    """#!/bin/sh
python3 - "$SSHGO_FAKE_SSH_ARGS" "$@" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(sys.argv[2:], f)
PY
exit 255
"""
                )
            os.chmod(fake_ssh, 0o755)
            env = os.environ.copy()
            env["PATH"] = temp_dir + os.pathsep + env.get("PATH", "")
            env["SSHGO_FAKE_SSH_ARGS"] = args_path

            subprocess.run(
                [
                    "sftp",
                    "-S",
                    os.path.join(os.getcwd(), "sftp_ssh_wrapper.py"),
                    "-b",
                    batch_path,
                    "targetuser@target.internal",
                ],
                cwd=os.getcwd(),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

            with open(args_path, "r", encoding="utf-8") as f:
                args = json.load(f)
            rendered = " ".join(args).lower()
            self.assertIn("batchmode=no", rendered)
            self.assertNotIn("batchmode yes", rendered)
            self.assertNotIn("batchmode=yes", rendered)

    def _run_sftp_with_fake_binary(
        self,
        mode,
        action="upload",
        local_path="local.txt",
        remote_path="/tmp/remote.txt",
        target_pass=None,
        mfa_secret=None,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_sftp = os.path.join(temp_dir, "sftp")
            meta_path = os.path.join(temp_dir, "meta.json")
            with open(fake_sftp, "w", encoding="utf-8") as f:
                f.write(
                    """#!/bin/sh
mode="${SSHGO_FAKE_SFTP_MODE:-success}"
batch=""
has_batch=0
has_wrapper=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        "-b")
            has_batch=1
            shift
            batch="${1:-}"
            ;;
        "-S")
            has_wrapper=1
            shift
            ;;
    esac
    shift
done
if [ -n "${SSHGO_FAKE_SFTP_META:-}" ]; then
    python3 - "$batch" "$SSHGO_FAKE_SFTP_META" "$has_batch" "$has_wrapper" <<'PY'
import json
import os
import stat
import sys

batch_path, meta_path = sys.argv[1], sys.argv[2]
exists = bool(batch_path) and os.path.exists(batch_path)
data = {
    "batch_path": batch_path,
    "has_batch": sys.argv[3] == "1",
    "has_wrapper": sys.argv[4] == "1",
    "batch_exists_during": exists,
    "batch_mode": (
        f"{stat.S_IMODE(os.stat(batch_path).st_mode):04o}" if exists else None
    ),
    "batch_content": (
        open(batch_path, encoding="utf-8").read() if exists else ""
    ),
}
with open(meta_path, "w", encoding="utf-8") as f:
    json.dump(data, f)
PY
fi
if [ "$mode" = "connect_fail" ]; then
    echo "ssh: Could not resolve hostname target.internal"
    exit 255
fi
if [ "$mode" = "host_key_prompt" ]; then
    printf 'Are you sure you want to continue connecting (yes/no/[fingerprint])? '
    IFS= read -r answer
    if [ "$has_batch" = "0" ]; then
        printf 'sftp> '
    fi
    exit 0
fi
if [ "$mode" = "password_prompt" ]; then
    printf 'password: '
    IFS= read -r answer
    if [ "$has_batch" = "0" ]; then
        printf 'sftp> '
    fi
    exit 0
fi
if [ "$mode" = "mfa_prompt" ]; then
    printf 'Verification code: '
    IFS= read -r answer
    if [ "$has_batch" = "0" ]; then
        printf 'sftp> '
    fi
    exit 0
fi
if [ "$mode" = "transfer_fail" ]; then
    exit 1
fi
if [ "$mode" = "child_sigterm" ]; then
    kill -TERM $$
fi
if [ "$mode" = "remote_permission_fail" ]; then
    exit 1
fi
if [ "$mode" = "local_missing_fail" ]; then
    exit 1
fi
if [ "$mode" = "success_without_prompt" ]; then
    exit 0
fi
if [ "$has_batch" = "0" ]; then
    printf 'sftp> '
fi
exit 0
"""
                )
            os.chmod(fake_sftp, 0o755)

            env = os.environ.copy()
            env["PATH"] = temp_dir + os.pathsep + env.get("PATH", "")
            env["TMPDIR"] = temp_dir
            env["SSHGO_FAKE_SFTP_MODE"] = mode
            env["SSHGO_FAKE_SFTP_META"] = meta_path
            if target_pass:
                env["SSHGO_TARGET_PASS"] = target_pass
            if mfa_secret:
                env["SSHGO_MFA_SECRET"] = mfa_secret
            command = [
                "./sftp_login.exp",
                "-h",
                "target.internal",
                "-u",
                "targetuser",
                "-action",
                action,
            ]
            if action != "interactive":
                command.extend(["-local", local_path, "-remote", remote_path])
            result = subprocess.run(
                command,
                cwd=os.getcwd(),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )
            metadata = {}
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                batch_path = metadata.get("batch_path")
                metadata["batch_exists_after"] = (
                    bool(batch_path) and os.path.exists(batch_path)
                )
            result.sftp_meta = metadata
            return result

    def test_sftp_exp_exits_nonzero_when_session_fails_before_prompt(self):
        result = self._run_sftp_with_fake_binary("connect_fail")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "File transfer failed with exit status",
            result.stdout + result.stderr,
        )

    def test_sftp_exp_exits_nonzero_from_batch_exit_status(self):
        result = self._run_sftp_with_fake_binary("transfer_fail")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("File transfer failed", result.stdout + result.stderr)
        self.assertNotIn("Failure:", result.stdout + result.stderr)
        self.assertFalse(result.sftp_meta["batch_exists_after"])

    def test_sftp_exp_exits_nonzero_when_sftp_child_is_signaled(self):
        result = self._run_sftp_with_fake_binary("child_sigterm")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("File transfer failed", result.stdout + result.stderr)
        self.assertFalse(result.sftp_meta["batch_exists_after"])

    def test_sftp_exp_cleans_up_batch_when_spawn_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env = os.environ.copy()
            env["PATH"] = temp_dir
            env["TMPDIR"] = temp_dir
            result = subprocess.run(
                [
                    "./sftp_login.exp",
                    "-h",
                    "target.internal",
                    "-u",
                    "targetuser",
                    "-action",
                    "upload",
                    "-local",
                    "local.txt",
                    "-remote",
                    "/tmp/remote.txt",
                ],
                cwd=os.getcwd(),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Error executing sftp", result.stdout + result.stderr)
            self.assertFalse(
                any(name.startswith("sshgo-sftp-") for name in os.listdir(temp_dir))
            )

    def test_sftp_exp_cleans_up_batch_on_sigterm(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_sftp = os.path.join(temp_dir, "sftp")
            meta_path = os.path.join(temp_dir, "meta.json")
            with open(fake_sftp, "w", encoding="utf-8") as f:
                f.write(
                    """#!/bin/sh
batch=""
while [ "$#" -gt 0 ]; do
    if [ "$1" = "-b" ]; then
        shift
        batch="${1:-}"
        break
    fi
    shift
done
python3 - "$batch" "$SSHGO_FAKE_SFTP_META" <<'PY'
import json
import os
import sys

batch_path, meta_path = sys.argv[1], sys.argv[2]
with open(meta_path, "w", encoding="utf-8") as f:
    json.dump({"batch_path": batch_path, "exists": os.path.exists(batch_path)}, f)
PY
sleep 30
exit 0
"""
                )
            os.chmod(fake_sftp, 0o755)

            env = os.environ.copy()
            env["PATH"] = temp_dir + os.pathsep + env.get("PATH", "")
            env["TMPDIR"] = temp_dir
            env["SSHGO_FAKE_SFTP_META"] = meta_path
            proc = subprocess.Popen(
                [
                    "./sftp_login.exp",
                    "-h",
                    "target.internal",
                    "-u",
                    "targetuser",
                    "-action",
                    "upload",
                    "-local",
                    "local.txt",
                    "-remote",
                    "/tmp/remote.txt",
                ],
                cwd=os.getcwd(),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            try:
                for _ in range(200):
                    if os.path.exists(meta_path):
                        break
                    if proc.poll() is not None:
                        break
                    time.sleep(0.05)
                if not os.path.exists(meta_path):
                    stdout, stderr = proc.communicate(timeout=5)
                    self.fail(
                        "fake sftp did not write metadata; "
                        f"returncode={proc.returncode}; "
                        f"stdout={stdout}; stderr={stderr}; "
                        f"files={os.listdir(temp_dir)}"
                    )
                with open(meta_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                self.assertTrue(metadata["exists"])

                os.killpg(proc.pid, signal.SIGTERM)
                stdout, stderr = proc.communicate(timeout=5)

                self.assertNotEqual(proc.returncode, 0)
                self.assertFalse(
                    any(name.startswith("sshgo-sftp-") for name in os.listdir(temp_dir)),
                    stdout + stderr,
                )
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate(timeout=5)
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

    def test_sftp_exp_does_not_treat_error_words_in_paths_as_failure(self):
        result = self._run_sftp_with_fake_binary(
            "success",
            local_path="local-error.txt",
            remote_path="/tmp/remote-failed.txt",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sftp_exp_creates_0600_single_command_batch_and_cleans_up(self):
        upload = self._run_sftp_with_fake_binary("success")
        self.assertEqual(upload.returncode, 0, upload.stdout + upload.stderr)
        self.assertTrue(upload.sftp_meta["batch_exists_during"])
        self.assertEqual(upload.sftp_meta["batch_mode"], "0600")
        self.assertEqual(
            upload.sftp_meta["batch_content"],
            'put "local.txt" "/tmp/remote.txt"\n',
        )
        self.assertFalse(upload.sftp_meta["batch_exists_after"])

        download = self._run_sftp_with_fake_binary(
            "success",
            action="download",
            local_path="local.txt",
            remote_path="/tmp/remote.txt",
        )
        self.assertEqual(download.returncode, 0, download.stdout + download.stderr)
        self.assertEqual(
            download.sftp_meta["batch_content"],
            'get "/tmp/remote.txt" "local.txt"\n',
        )
        self.assertFalse(download.sftp_meta["batch_exists_after"])

    def test_sftp_exp_writes_utf8_paths_to_batch(self):
        result = self._run_sftp_with_fake_binary(
            "success",
            local_path="./测试文件.zip",
            remote_path="/remote/测试文件.zip",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            result.sftp_meta["batch_content"],
            'put "./测试文件.zip" "/remote/测试文件.zip"\n',
        )

    def test_sftp_exp_removes_stale_batch_files_before_transfer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stale_path = os.path.join(temp_dir, "sshgo-sftp-stale.batch")
            with open(stale_path, "w", encoding="utf-8") as f:
                f.write('put "old" "old"\n')
            stale_dir = os.path.join(temp_dir, "sshgo-sftp-dir.batch")
            os.mkdir(stale_dir)
            old_time = time.time() - 90000
            os.utime(stale_path, (old_time, old_time))
            os.utime(stale_dir, (old_time, old_time))

            fake_sftp = os.path.join(temp_dir, "sftp")
            meta_path = os.path.join(temp_dir, "meta.json")
            with open(fake_sftp, "w", encoding="utf-8") as f:
                f.write(
                    """#!/bin/sh
batch=""
while [ "$#" -gt 0 ]; do
    if [ "$1" = "-b" ]; then
        shift
        batch="${1:-}"
        break
    fi
    shift
done
python3 - "$batch" "$SSHGO_FAKE_SFTP_META" <<'PY'
import json
import os
import sys

batch_path, meta_path = sys.argv[1], sys.argv[2]
with open(meta_path, "w", encoding="utf-8") as f:
    json.dump({"batch_path": batch_path, "exists": os.path.exists(batch_path)}, f)
PY
exit 0
"""
                )
            os.chmod(fake_sftp, 0o755)

            env = os.environ.copy()
            env["PATH"] = temp_dir + os.pathsep + env.get("PATH", "")
            env["TMPDIR"] = temp_dir
            env["SSHGO_FAKE_SFTP_META"] = meta_path
            result = subprocess.run(
                [
                    "./sftp_login.exp",
                    "-h",
                    "target.internal",
                    "-u",
                    "targetuser",
                    "-action",
                    "upload",
                    "-local",
                    "local.txt",
                    "-remote",
                    "/tmp/remote.txt",
                ],
                cwd=os.getcwd(),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(os.path.exists(stale_path))
            self.assertTrue(os.path.isdir(stale_dir))
            remaining_batch_files = [
                name
                for name in os.listdir(temp_dir)
                if (
                    name.startswith("sshgo-sftp-")
                    and os.path.isfile(os.path.join(temp_dir, name))
                )
            ]
            self.assertEqual(remaining_batch_files, [])

    def test_sftp_exp_batch_mode_handles_auth_prompts(self):
        cases = [
            ("host_key_prompt", {}),
            ("password_prompt", {"target_pass": "target-pass"}),
            ("mfa_prompt", {"mfa_secret": "JBSWY3DPEHPK3PXP"}),
        ]
        for mode, kwargs in cases:
            with self.subTest(mode=mode):
                result = self._run_sftp_with_fake_binary(mode, **kwargs)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sftp_exp_interactive_mode_omits_batch_and_wrapper(self):
        result = self._run_sftp_with_fake_binary("success", action="interactive")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("interactive sftp", result.stdout + result.stderr)
        self.assertFalse(result.sftp_meta["has_batch"])
        self.assertFalse(result.sftp_meta["has_wrapper"])
        self.assertEqual(result.sftp_meta["batch_path"], "")
        self.assertFalse(result.sftp_meta["batch_exists_after"])

    def test_sftp_exp_interactive_mode_preserves_utf8_user_input(self):
        command = "put ./测试文件.zip /remote/测试文件.zip"
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_sftp = os.path.join(temp_dir, "sftp")
            meta_path = os.path.join(temp_dir, "meta.json")
            with open(fake_sftp, "w", encoding="utf-8") as f:
                f.write(
                    """#!/bin/sh
printf 'sftp> '
IFS= read -r command
python3 - "$SSHGO_FAKE_SFTP_META" "$command" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump({"interactive_command": sys.argv[2]}, f, ensure_ascii=False)
PY
exit 0
"""
                )
            os.chmod(fake_sftp, 0o755)

            env = os.environ.copy()
            env["PATH"] = temp_dir + os.pathsep + env.get("PATH", "")
            env["SSHGO_FAKE_SFTP_META"] = meta_path
            master_fd, slave_fd = pty.openpty()
            proc = subprocess.Popen(
                [
                    "./sftp_login.exp",
                    "-h",
                    "target.internal",
                    "-u",
                    "targetuser",
                    "-action",
                    "interactive",
                ],
                cwd=os.getcwd(),
                env=env,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
            )
            os.close(slave_fd)
            output = b""
            try:
                deadline = time.time() + 5
                while b"sftp> " not in output and time.time() < deadline:
                    ready, _, _ = select.select([master_fd], [], [], 0.1)
                    if master_fd not in ready:
                        continue
                    try:
                        chunk = os.read(master_fd, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output += chunk

                self.assertIn(b"sftp> ", output)
                os.write(master_fd, (command + "\n").encode("utf-8"))
                returncode = proc.wait(timeout=5)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
                os.close(master_fd)

            self.assertEqual(returncode, 0, output.decode("utf-8", "replace"))
            with open(meta_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
            self.assertEqual(metadata["interactive_command"], command)

    def test_sftp_exp_interactive_mode_handles_auth_prompts(self):
        cases = [
            ("host_key_prompt", {}),
            ("password_prompt", {"target_pass": "target-pass"}),
            ("mfa_prompt", {"mfa_secret": "JBSWY3DPEHPK3PXP"}),
        ]
        for mode, kwargs in cases:
            with self.subTest(mode=mode):
                result = self._run_sftp_with_fake_binary(
                    mode,
                    action="interactive",
                    **kwargs,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(result.sftp_meta["has_batch"])
                self.assertFalse(result.sftp_meta["has_wrapper"])

    def test_sftp_exp_interactive_mode_fails_before_prompt(self):
        result = self._run_sftp_with_fake_binary("connect_fail", action="interactive")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Interactive SFTP exited", result.stdout + result.stderr)
        self.assertFalse(result.sftp_meta["has_batch"])
        self.assertFalse(result.sftp_meta["has_wrapper"])

    def test_sftp_exp_interactive_mode_fails_on_clean_eof_before_prompt(self):
        result = self._run_sftp_with_fake_binary(
            "success_without_prompt",
            action="interactive",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "Interactive SFTP ended before prompt",
            result.stdout + result.stderr,
        )
        self.assertFalse(result.sftp_meta["has_batch"])
        self.assertFalse(result.sftp_meta["has_wrapper"])

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

    def test_interactive_sftp_exec_failure_is_audited(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")

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
                        manager.execute_interactive_sftp_session(target)
            finally:
                host_manager_module.os.execve = real_execve

            self.assertTrue(captured["path"].endswith("sftp_login.exp"))
            self.assertEqual(
                captured["args"][captured["args"].index("-action") + 1],
                "interactive",
            )
            self.assertNotIn("-local", captured["args"])
            self.assertNotIn("-remote", captured["args"])
            self.assertEqual(captured["env"]["SSHGO_TARGET_PASS"], "target-pass")
            self.assertEqual(captured["env"]["SSHGO_JUMPER_PASS"], "jump-pass")

            with open(manager.audit.audit_simple_path, "r", encoding="utf-8") as f:
                records = [json.loads(line) for line in f if line.strip()]
            self.assertTrue(
                any(r["result"] == "sftp_interactive_started" for r in records)
            )
            self.assertTrue(
                any(
                    r["result"] == "sftp_interactive_exec_failed:5"
                    for r in records
                )
            )

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
