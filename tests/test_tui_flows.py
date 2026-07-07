import unittest

from i18n import i18n
import tui_flows


class TuiFlowsTests(unittest.TestCase):
    def test_count_descendants_counts_nested_children(self):
        node = {
            "type": "group",
            "children": [
                {"type": "host"},
                {
                    "type": "group",
                    "children": [
                        {"type": "host"},
                        {"type": "host"},
                    ],
                },
            ],
        }

        self.assertEqual(tui_flows.count_descendants(node), 4)

    def test_delete_impact_text_describes_group_size(self):
        tui = object()
        node = {
            "type": "group",
            "children": [
                {"type": "host"},
                {"type": "host"},
            ],
        }

        impact = tui_flows.delete_impact_text(tui, node)

        self.assertIn("2", impact)

    def test_delete_impact_text_describes_host_target(self):
        class FakeManager:
            def raw_host_port(self, node):
                return node["host"], node.get("port")

            def _target_display(self, user, host, port):
                return f"{user}@{host}:{port}"

        tui = type("FakeTui", (), {"host_manager": FakeManager()})()
        node = {
            "type": "host",
            "host": "target.internal",
            "port": "2222",
            "user": "targetuser",
        }

        impact = tui_flows.delete_impact_text(tui, node)

        self.assertIn("targetuser@target.internal:2222", impact)

    def test_show_save_error_uses_manager_save_error(self):
        messages = []
        manager = type("FakeManager", (), {"last_save_error": "stale write"})()

        class FakeTui:
            host_manager = manager

            def _show_message(self, title, message):
                messages.append((title, message))

        tui_flows.show_save_error(FakeTui())

        self.assertEqual(messages, [(i18n.get("error_title"), "stale write")])


if __name__ == "__main__":
    unittest.main()
