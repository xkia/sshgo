import os
import shlex
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from connection_errors import ConfigRuntimeError
from connection_plan import CommandPlan
from connection_planner import ConnectionPlanner

try:
    from fixtures import host, jump_with_target, manager_for_config
except ModuleNotFoundError:
    from tests.fixtures import host, jump_with_target, manager_for_config


class CommandPlanTests(unittest.TestCase):
    def _planner(self, manager):
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return ConnectionPlanner(manager, script_dir)

    def _manager(self, temp_dir):
        return manager_for_config(
            temp_dir,
            hosts=[
                jump_with_target(),
                host(
                    "direct",
                    "direct.example.com",
                    user="directuser",
                    port="2201",
                    password="direct-pass",
                ),
            ],
        )

    def test_interactive_command_plan_contains_launch_env_and_audit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")

            plan = self._planner(manager).build_interactive_command_plan(
                target,
                "uptime",
            )

            self.assertIsInstance(plan, CommandPlan)
            self.assertTrue(plan.script_path.endswith("login.exp"))
            self.assertEqual(plan.launch_args()[0], plan.script_path)
            self.assertIn("-c", plan.args)
            self.assertEqual(plan.args[plan.args.index("-c") + 1], "uptime")
            self.assertEqual(plan.secret_env["SSHGO_TARGET_PASS"], "target-pass")
            self.assertEqual(plan.secret_env["SSHGO_JUMPER_PASS"], "jump-pass")
            self.assertEqual(plan.audit["name"], "target")
            self.assertEqual(plan.audit["host"], "target.internal")
            self.assertEqual(plan.audit["command"], "uptime")
            self.assertEqual(plan.audit["jump_chain"], ["jump"])
            self.assertEqual(plan.audit["extra"]["ssh_jump_mode"], "shell")
            self.assertEqual(
                manager.build_interactive_launch_command_args(target, "uptime"),
                plan.launch_args(),
            )

    def test_launch_arg_preview_does_not_emit_terminal_title(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            manager.config.update({
                "terminal_title_enabled": True,
                "terminal_title_scope": "always",
            })
            target = manager.find_host_by_alias("target")

            stdout = StringIO()
            with redirect_stdout(stdout):
                args = manager.build_interactive_launch_command_args(target, "uptime")

            self.assertTrue(args[0].endswith("login.exp"))
            self.assertEqual(stdout.getvalue(), "")

    def test_ipv6_interactive_command_plan_formats_endpoint_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = manager_for_config(
                temp_dir,
                hosts=[
                    host(
                        "ipv6",
                        "2001:db8::10",
                        user="deploy",
                        port="2200",
                        password="pw",
                    )
                ],
            )
            target = manager.find_host_by_alias("ipv6")

            plan = self._planner(manager).build_interactive_command_plan(target)

            self.assertEqual(plan.args[plan.args.index("-h") + 1], "2001:db8::10")
            self.assertEqual(plan.args[plan.args.index("-p") + 1], "2200")
            self.assertEqual(plan.audit["host"], "2001:db8::10")
            self.assertEqual(plan.audit["port"], "2200")
            self.assertEqual(plan.audit["endpoint"], "[2001:db8::10]:2200")

    def test_ipv6_jump_endpoint_is_bracketed_in_tunnel_arguments(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = manager_for_config(
                temp_dir,
                config={
                    "import_ssh_config": False,
                    "default_ssh_jump_mode": "tunnel",
                    "default_transfer_jump_mode": "tunnel",
                },
                hosts=[
                    jump_with_target(
                        jump_name="jump6",
                        jump_host="2001:db8::1",
                        target_port=None,
                        target_id_file=None,
                        target_mfa_secret=None,
                    )
                ],
            )
            target = manager.find_host_by_alias("target")

            plan = self._planner(manager).build_interactive_command_plan(target)
            proxy_command = plan.args[plan.args.index("-tunnel-proxy-command") + 1]

            self.assertEqual(
                plan.args[plan.args.index("-J") + 1],
                "jumpuser@[2001:db8::1]:2200",
            )
            self.assertIn("-p 2200", proxy_command)
            self.assertIn("jumpuser@2001:db8::1", proxy_command)
            self.assertNotIn("jumpuser@[2001:db8::1]", proxy_command)

    def test_ipv6_tunnel_target_brackets_forward_spec(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = manager_for_config(
                temp_dir,
                config={
                    "import_ssh_config": False,
                    "default_ssh_jump_mode": "tunnel",
                    "default_transfer_jump_mode": "tunnel",
                },
                hosts=[
                    jump_with_target(
                        target_name="target6",
                        target_host="2001:db8::10",
                        target_port="2201",
                        target_id_file=None,
                        target_mfa_secret=None,
                    )
                ],
            )
            target = manager.find_host_by_alias("target6")

            plan = self._planner(manager).build_interactive_command_plan(target)
            proxy_command = plan.args[plan.args.index("-tunnel-proxy-command") + 1]
            proxy_parts = shlex.split(proxy_command)

            self.assertEqual(proxy_parts[proxy_parts.index("-W") + 1], "[%h]:%p")
            self.assertEqual(plan.args[plan.args.index("-h") + 1], "2001:db8::10")
            self.assertEqual(plan.args[plan.args.index("-p") + 1], "2201")

    def test_ipv6_sftp_tunnel_target_uses_unbracketed_forward_spec(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = manager_for_config(
                temp_dir,
                config={
                    "import_ssh_config": False,
                    "default_transfer_jump_mode": "tunnel",
                },
                hosts=[
                    jump_with_target(
                        target_name="target6",
                        target_host="2001:db8::10",
                        target_port="2201",
                        target_id_file=None,
                        target_mfa_secret=None,
                    )
                ],
            )
            target = manager.find_host_by_alias("target6")

            plan = self._planner(manager).build_file_transfer_command_plan(
                target,
                "upload",
                "local.txt",
                "/tmp/remote.txt",
            )
            proxy_command = plan.args[plan.args.index("-tunnel-proxy-command") + 1]
            proxy_parts = shlex.split(proxy_command)

            self.assertEqual(proxy_parts[proxy_parts.index("-W") + 1], "%h:%p")
            self.assertEqual(plan.args[plan.args.index("-h") + 1], "2001:db8::10")
            self.assertEqual(plan.args[plan.args.index("-P") + 1], "2201")

    def test_sftp_command_plan_contains_transfer_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")

            plan = self._planner(manager).build_file_transfer_command_plan(
                target,
                "download",
                "/remote/file.txt",
                "local-file.txt",
            )

            self.assertIsInstance(plan, CommandPlan)
            self.assertTrue(plan.script_path.endswith("sftp_login.exp"))
            self.assertEqual(plan.start_result, "sftp_started")
            self.assertEqual(plan.args[plan.args.index("-action") + 1], "download")
            self.assertEqual(
                plan.args[plan.args.index("-local") + 1],
                "local-file.txt",
            )
            self.assertEqual(
                plan.args[plan.args.index("-remote") + 1],
                "/remote/file.txt",
            )
            self.assertEqual(plan.secret_env["SSHGO_TARGET_PASS"], "target-pass")
            self.assertEqual(plan.secret_env["SSHGO_JUMPER_PASS"], "jump-pass")
            self.assertEqual(
                plan.audit["command"],
                "download /remote/file.txt local-file.txt",
            )
            self.assertEqual(plan.audit["extra"]["transfer_jump_mode"], "tunnel")
            self.assertEqual(
                manager.build_file_transfer_launch_command_args(
                    target,
                    "download",
                    "/remote/file.txt",
                    "local-file.txt",
                ),
                plan.launch_args(),
            )

    def test_interactive_sftp_command_plan_uses_direct_sftp_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("direct")

            plan = self._planner(manager).build_interactive_sftp_command_plan(target)

            self.assertIsInstance(plan, CommandPlan)
            self.assertTrue(plan.script_path.endswith("sftp_login.exp"))
            self.assertEqual(plan.start_result, "sftp_interactive_started")
            self.assertEqual(plan.missing_result, "sftp_interactive_exp_not_found")
            self.assertEqual(plan.args[plan.args.index("-action") + 1], "interactive")
            self.assertNotIn("-local", plan.args)
            self.assertNotIn("-remote", plan.args)
            self.assertNotIn("-J", plan.args)
            self.assertNotIn("-tunnel-proxy-command", plan.args)
            self.assertEqual(plan.secret_env["SSHGO_TARGET_PASS"], "direct-pass")
            self.assertEqual(plan.audit["command"], "sftp")
            self.assertEqual(plan.audit["extra"]["transfer_jump_mode"], "direct")
            self.assertTrue(plan.audit["extra"]["interactive"])
            self.assertEqual(
                manager.build_interactive_sftp_launch_command_args(target),
                plan.launch_args(),
            )

    def test_interactive_sftp_command_plan_uses_tunnel_for_nested_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")

            plan = self._planner(manager).build_interactive_sftp_command_plan(target)

            self.assertTrue(plan.script_path.endswith("sftp_login.exp"))
            self.assertEqual(plan.args[plan.args.index("-action") + 1], "interactive")
            self.assertIn("-tunnel-proxy-command", plan.args)
            self.assertEqual(plan.audit["jump_chain"], ["jump"])
            self.assertEqual(plan.audit["extra"]["transfer_jump_mode"], "tunnel")
            self.assertEqual(plan.secret_env["SSHGO_TARGET_PASS"], "target-pass")
            self.assertEqual(plan.secret_env["SSHGO_JUMPER_PASS"], "jump-pass")

    def test_interactive_sftp_rejects_relay_transfer_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")
            target["transfer_jump_mode"] = "relay"

            with self.assertRaisesRegex(ConfigRuntimeError, "Interactive SFTP"):
                self._planner(manager).build_interactive_sftp_command_plan(target)

    def test_relay_command_plan_contains_relay_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")
            target["transfer_jump_mode"] = "relay"

            plan = self._planner(manager).build_file_transfer_command_plan(
                target,
                "upload",
                "local.txt",
                "/tmp/remote.txt",
            )

            self.assertIsInstance(plan, CommandPlan)
            self.assertTrue(plan.script_path.endswith("relay_transfer.exp"))
            self.assertEqual(plan.start_result, "relay_upload_started")
            self.assertEqual(plan.missing_result, "relay_exp_not_found")
            self.assertEqual(plan.args[plan.args.index("-action") + 1], "upload")
            self.assertIn("-temp", plan.args)
            self.assertEqual(plan.secret_env["SSHGO_TARGET_PASS"], "target-pass")
            self.assertEqual(plan.secret_env["SSHGO_JUMPER_PASS"], "jump-pass")
            self.assertEqual(plan.audit["jump_chain"], ["jump"])
            self.assertEqual(plan.audit["extra"]["transfer_jump_mode"], "relay")
            launch_args = manager.build_file_transfer_launch_command_args(
                target,
                "upload",
                "local.txt",
                "/tmp/remote.txt",
            )
            self.assertTrue(launch_args[0].endswith("relay_transfer.exp"))
            self.assertIn("-temp", launch_args)

    def test_file_transfer_plan_uses_transfer_mode_dispatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")
            target["transfer_jump_mode"] = "relay"

            plan = self._planner(manager).build_file_transfer_command_plan(
                target,
                "upload",
                "local.txt",
                "/tmp/remote.txt",
            )
            args = plan.args

            self.assertIn("-temp", args)
            self.assertIn("-J-host", args)
            self.assertNotIn("-tunnel-proxy-command", args)

    def test_explicit_sftp_plan_stays_sftp_only_for_relay_nodes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            planner = self._planner(manager)
            target = manager.find_host_by_alias("target")
            target["transfer_jump_mode"] = "relay"

            file_plan = planner.build_file_transfer_command_plan(
                target,
                "upload",
                "local.txt",
                "/tmp/remote.txt",
            )
            sftp_plan = planner.build_sftp_command_plan(
                target,
                "upload",
                "local.txt",
                "/tmp/remote.txt",
            )

            self.assertIn("-temp", file_plan.args)
            self.assertNotIn("-temp", sftp_plan.args)
            self.assertIn("-tunnel-proxy-command", sftp_plan.args)


if __name__ == "__main__":
    unittest.main()
