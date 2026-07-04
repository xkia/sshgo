import json
import os
import pty
import select
import signal
import subprocess
import tempfile
import time
import unittest


class SftpExpectTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
