import json
import os
import tempfile
import unittest

from host_manager import CommandPlan, HostManager


class CommandPlanTests(unittest.TestCase):
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

    def test_interactive_command_plan_contains_launch_env_and_audit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")

            plan = manager.build_interactive_command_plan(target, "uptime")

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

    def test_sftp_command_plan_contains_transfer_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")

            plan = manager.build_file_transfer_command_plan(
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

    def test_relay_command_plan_contains_relay_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            target = manager.find_host_by_alias("target")
            target["transfer_jump_mode"] = "relay"

            plan = manager.build_file_transfer_command_plan(
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


if __name__ == "__main__":
    unittest.main()
