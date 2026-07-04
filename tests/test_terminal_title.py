import unittest
from io import StringIO
from types import SimpleNamespace

from terminal_title import (
    emit_terminal_title,
    sanitize_terminal_title,
    terminal_title_for_plan,
)


def _plan(start_result="started", command=None):
    return SimpleNamespace(
        start_result=start_result,
        audit={
            "name": "demo",
            "host": "example.com",
            "port": "22",
            "endpoint": "example.com:22",
            "command": command,
        },
    )


class BrokenOutput:
    def write(self, value):
        raise UnicodeEncodeError("ascii", value, 0, 1, "fake")

    def flush(self):
        raise AssertionError("flush should not run after write failure")


class TerminalTitleTests(unittest.TestCase):
    def test_emit_swallow_encoding_error(self):
        config = {
            "terminal_title_enabled": True,
            "terminal_title_scope": "always",
        }

        emitted = emit_terminal_title(config, _plan(), output=BrokenOutput())

        self.assertFalse(emitted)

    def test_sanitize_strips_control_characters(self):
        self.assertEqual(
            sanitize_terminal_title("a\x00\x1b\x07\x7f\x80\x9fb"),
            "ab",
        )

    def test_window_and_both_targets(self):
        base_config = {
            "terminal_title_enabled": True,
            "terminal_title_scope": "always",
        }

        window_output = StringIO()
        emit_terminal_title(
            {**base_config, "terminal_title_target": "window"},
            _plan(),
            output=window_output,
        )
        both_output = StringIO()
        emit_terminal_title(
            {**base_config, "terminal_title_target": "both"},
            _plan(),
            output=both_output,
        )

        self.assertEqual(window_output.getvalue(), "\033]2;SSH demo | example.com\007")
        self.assertEqual(both_output.getvalue(), "\033]0;SSH demo | example.com\007")

    def test_alias_only_format(self):
        title = terminal_title_for_plan(
            {"terminal_title_format": "alias"},
            _plan(),
        )

        self.assertEqual(title, "SSH demo")

    def test_transfer_mode_prefixes(self):
        upload_title = terminal_title_for_plan(
            {},
            _plan(start_result="sftp_started", command="upload local remote"),
        )
        relay_title = terminal_title_for_plan(
            {},
            _plan(start_result="relay_download_started", command="download remote local"),
        )

        self.assertEqual(upload_title, "UPLOAD demo | example.com")
        self.assertEqual(relay_title, "RELAY DOWNLOAD demo | example.com")


if __name__ == "__main__":
    unittest.main()
