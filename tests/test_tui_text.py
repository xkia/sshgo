import unittest

import tui_text


class TuiTextTests(unittest.TestCase):
    def test_ellipsize_head_and_tail(self):
        self.assertEqual(tui_text.ellipsize("abcdef", 4), "a...")
        self.assertEqual(tui_text.ellipsize("abcdef", 4, tail=True), "...f")
        self.assertEqual(tui_text.ellipsize("abcdef", 3), "abc")
        self.assertEqual(tui_text.ellipsize("abcdef", 0), "")

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


if __name__ == "__main__":
    unittest.main()
