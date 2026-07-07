import unittest

from i18n import i18n
import tui_render


class FakeWindow:
    def __init__(self, height=8, width=40):
        self.height = height
        self.width = width
        self.addstr_calls = []
        self.border_calls = 0
        self.clear_calls = 0

    def getmaxyx(self):
        return (self.height, self.width)

    def addstr(self, *args):
        self.addstr_calls.append(args)

    def border(self, *args):
        self.border_calls += 1

    def clear(self):
        self.clear_calls += 1


class TuiRenderTests(unittest.TestCase):
    def test_safe_addstr_truncates_to_available_width(self):
        window = FakeWindow(width=8)

        tui_render.safe_addstr(window, 0, 1, "abcdefg")
        tui_render.safe_addstr(window, 0, 99, "hidden")

        self.assertEqual(len(window.addstr_calls), 1)
        self.assertEqual(window.addstr_calls[0][2], "abcde")

    def test_draw_shell_draws_frame_search_and_footer(self):
        window = FakeWindow(height=6, width=30)

        layout = tui_render.draw_shell(
            window,
            title="Hosts",
            footer="Footer",
            search_text="Search",
            frame=True,
            status_attr=7,
        )

        rendered = [call[2] for call in window.addstr_calls]
        self.assertEqual(window.clear_calls, 1)
        self.assertEqual(window.border_calls, 1)
        self.assertEqual(layout["search_y"], 4)
        self.assertEqual(layout["footer_y"], 5)
        self.assertTrue(any("Hosts" in text for text in rendered))
        self.assertIn("Search", rendered)
        self.assertIn("Footer", rendered)

    def test_main_split_layout_requires_host_and_enabled_detail_pane(self):
        host_node = {"type": "host", "name": "target"}

        wide = tui_render.main_split_layout(120, host_node)
        no_host = tui_render.main_split_layout(120, {"type": "group"})
        disabled = tui_render.main_split_layout(
            120,
            host_node,
            show_detail_pane=False,
        )

        self.assertEqual(wide["separator_x"], 78)
        self.assertEqual(wide["detail_x"], 79)
        self.assertIsNone(no_host["detail_x"])
        self.assertIsNone(disabled["detail_x"])

    def test_draw_detail_pane_renders_host_details(self):
        window = FakeWindow(height=8, width=36)

        tui_render.draw_detail_pane(
            window,
            {"type": "host", "name": "target"},
            [("Target", "targetuser@target.internal:2222")],
        )

        rendered = [call[2] for call in window.addstr_calls]
        self.assertEqual(window.clear_calls, 1)
        self.assertEqual(window.border_calls, 1)
        self.assertIn(i18n.get("host_details_title"), rendered)
        self.assertIn("Target:", rendered)
        self.assertTrue(any("targetuser@" in text for text in rendered))

    def test_draw_detail_pane_handles_missing_host(self):
        window = FakeWindow(height=8, width=36)

        tui_render.draw_detail_pane(window, None, [])

        rendered = [call[2] for call in window.addstr_calls]
        self.assertIn(i18n.get("select_host_details"), rendered)


if __name__ == "__main__":
    unittest.main()
