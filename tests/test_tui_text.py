import curses
import unittest

import tui_text


class TuiTextTests(unittest.TestCase):
    def test_ellipsize_head_and_tail(self):
        self.assertEqual(tui_text.ellipsize("abcdef", 4), "a...")
        self.assertEqual(tui_text.ellipsize("abcdef", 4, tail=True), "...f")
        self.assertEqual(tui_text.ellipsize("abcdef", 3), "abc")
        self.assertEqual(tui_text.ellipsize("abcdef", 0), "")

    def test_ellipsize_respects_wide_character_cells(self):
        self.assertEqual(tui_text.display_width("主机"), 4)
        self.assertEqual(tui_text.ellipsize("主机abc", 5), "主...")
        self.assertEqual(tui_text.ellipsize("abc主机", 5, tail=True), "...机")
        self.assertEqual(tui_text.truncate_cells("主机", 3), "主")

    def test_text_viewport_uses_display_cells_for_wide_characters(self):
        visible, cursor_x = tui_text.text_viewport("ab主机", 4, 4)
        self.assertEqual(visible, "主机")
        self.assertEqual(cursor_x, 4)

        visible, cursor_x = tui_text.text_viewport("主机abc", 1, 4)
        self.assertEqual(visible, "主机")
        self.assertEqual(cursor_x, 2)

    def test_insertable_text_filters_non_printable(self):
        self.assertEqual(tui_text.insertable_text_for_key("a\nb"), "ab")
        self.assertEqual(tui_text.insertable_text_for_key(65), "A")
        self.assertEqual(tui_text.insertable_text_for_key(9), "")

    def test_apply_text_edit_key_edits_and_reports_actions(self):
        value, cursor, action = tui_text.apply_text_edit_key("ab", 1, "X")
        self.assertEqual((value, cursor, action), ("aXb", 2, None))

        value, cursor, action = tui_text.apply_text_edit_key(value, cursor, 127)
        self.assertEqual((value, cursor, action), ("ab", 1, None))

        self.assertEqual(
            tui_text.apply_text_edit_key("done", 4, "\n")[2],
            "commit",
        )
        self.assertEqual(
            tui_text.apply_text_edit_key("done", 4, 27)[2],
            "cancel",
        )

    def test_apply_text_edit_key_cursor_control_delete_and_paste(self):
        cases = [
            ("abc", 3, curses.KEY_LEFT, ("abc", 2, None)),
            ("abXc", 3, "\x01", ("abXc", 0, None)),
            ("abXc", 0, ">", (">abXc", 1, None)),
            (">abXc", 1, "\x05", (">abXc", 5, None)),
            (">abXc", 5, curses.KEY_BACKSPACE, (">abX", 4, None)),
            ("abcd", 2, curses.KEY_DC, ("abd", 2, None)),
            ("ab", 1, "xy", ("axyb", 3, None)),
            ("axyb", 3, "\x15", ("", 0, None)),
        ]
        for value, cursor, key, expected in cases:
            with self.subTest(key=key):
                self.assertEqual(
                    tui_text.apply_text_edit_key(value, cursor, key),
                    expected,
                )


if __name__ == "__main__":
    unittest.main()
