import tempfile
import unittest

from i18n import i18n
from tui import Tui
import tui_recent

try:
    from fixtures import host, jump_with_target, manager_for_config
except ModuleNotFoundError:
    from tests.fixtures import host, jump_with_target, manager_for_config


class TuiRecentTests(unittest.TestCase):
    def test_recent_group_uses_current_name_after_rename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = manager_for_config(temp_dir, hosts=[jump_with_target()])
            manager.audit.record_login(
                "target",
                "target.internal",
                "targetuser",
                "password",
                "started",
            )
            manager.update_node(
                "target",
                {
                    "name": "renamed-target",
                    "host": "target.internal",
                    "port": "2222",
                    "user": "targetuser",
                },
            )

            recent_group = tui_recent.build_recent_group(manager)

        recent_names = [child["name"] for child in recent_group.get("children", [])]
        self.assertIn("renamed-target", recent_names)
        self.assertNotIn("target", recent_names)

    def test_recent_group_is_collapsed_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = manager_for_config(temp_dir, hosts=[jump_with_target()])
            manager.audit.record_login(
                "target",
                "target.internal",
                "targetuser",
                "password",
                "started",
            )

            recent_group = tui_recent.build_recent_group(manager)

        self.assertFalse(recent_group.get("expanded"))

    def test_recent_group_is_hidden_when_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = manager_for_config(temp_dir, hosts=[jump_with_target()])
            manager.config["show_recent"] = False
            manager.audit.record_login(
                "target",
                "target.internal",
                "targetuser",
                "password",
                "started",
            )

            tui = object.__new__(Tui)
            tui.host_manager = manager
            tui._recent_group = None
            tui._recent_group_ts = 0

            self.assertIsNone(Tui._build_recent_group(tui))
            self.assertNotIn(
                i18n.get("recent"),
                [node["name"] for node in Tui._get_all_nodes_with_level(tui)],
            )

    def test_recent_group_disable_clears_cached_group(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = manager_for_config(temp_dir, hosts=[jump_with_target()])
            manager.audit.record_login(
                "target",
                "target.internal",
                "targetuser",
                "password",
                "started",
            )
            tui = object.__new__(Tui)
            tui.host_manager = manager
            tui._recent_group = None
            tui._recent_group_ts = 0

            self.assertIsNotNone(Tui._build_recent_group(tui))
            manager.config["show_recent"] = False

            self.assertIsNone(Tui._build_recent_group(tui))
            self.assertIsNone(tui._recent_group)

    def test_recent_group_resolves_by_node_id_before_endpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = manager_for_config(
                temp_dir,
                hosts=[
                    host(
                        "app-22",
                        "shared.internal",
                        user="deploy",
                        password="pw",
                    ),
                    host(
                        "app-2222",
                        "shared.internal",
                        user="deploy",
                        port="2222",
                        password="pw",
                    ),
                ],
            )
            second = manager.find_host_by_alias("app-2222")
            manager.audit.record_login(
                "old-app",
                "shared.internal",
                "deploy",
                "password",
                "started",
                node_id=second["id"],
                port="2222",
                endpoint="shared.internal:2222",
            )
            manager.update_node(
                "app-2222",
                {
                    "name": "renamed-app",
                    "host": "shared.internal",
                    "port": "2222",
                    "user": "deploy",
                },
            )

            recent_group = tui_recent.build_recent_group(manager)

        recent_names = [child["name"] for child in recent_group.get("children", [])]
        self.assertEqual(recent_names, ["renamed-app"])

    def test_recent_group_falls_back_to_history_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = manager_for_config(temp_dir, hosts=[])
            manager.audit.record_login(
                "old-host",
                "2001:db8::10",
                "deploy",
                "password",
                "started",
                port="2222",
            )

            recent_group = tui_recent.build_recent_group(manager)

        child = recent_group["children"][0]
        self.assertEqual(child["name"], "old-host")
        self.assertEqual(child["host"], "[2001:db8::10]:2222")
        self.assertEqual(child["source"], "history")


if __name__ == "__main__":
    unittest.main()
