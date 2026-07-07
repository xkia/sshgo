import curses
import json
import os
import tempfile
import unittest
from io import StringIO

import tui as tui_module
import tui_flows
import tui_forms
from host_manager import HostManager
from i18n import i18n
from tui import Tui

try:
    from fixtures import jump_with_target, manager_for_config
except ImportError:
    from tests.fixtures import jump_with_target, manager_for_config


class TuiTests(unittest.TestCase):
    def _manager(self, temp_dir):
        return manager_for_config(temp_dir, hosts=[jump_with_target()])

    def test_form_reports_terminal_too_small(self):
        class FakeScreen:
            def __init__(self):
                self.messages = []

            def clear(self):
                pass

            def border(self, _):
                pass

            def getmaxyx(self):
                return (8, 20)

            def addstr(self, *args):
                for arg in args:
                    if isinstance(arg, str):
                        self.messages.append(arg)

            def refresh(self):
                pass

        tui = object.__new__(Tui)
        tui.screen = FakeScreen()
        tui.restore_screen = lambda: None
        result = Tui._draw_form(
            tui,
            [
                {"label": "Name", "type": "text", "name": "name", "y": 3, "x": 2},
                {"label": "Save", "type": "button", "y": 19, "x": 2},
            ],
            0,
            "Test",
        )

        self.assertFalse(result)
        self.assertTrue(
            any("Terminal too" in message for message in tui.screen.messages)
        )

    def test_form_layout_uses_single_dynamic_template(self):
        fields = [
            {
                "label": "Name",
                "type": "text",
                "name": "name",
                "y": 99,
                "x": 99,
            },
            {
                "label": "Auth Method",
                "type": "radio",
                "name": "auth",
                "options": ["password", "key"],
                "y": 99,
                "x": 99,
            },
            {"label": "Save", "type": "button", "y": 99, "x": 99},
            {"label": "Cancel", "type": "button", "y": 99, "x": 99},
        ]

        layout = tui_forms.layout_form_fields(fields, 100, start_y=2)

        self.assertGreaterEqual(layout["input_width"], 18)
        self.assertEqual(fields[0]["_screen_y"], 2)
        self.assertNotEqual(fields[0]["_label_x"], 99)
        self.assertGreater(fields[1]["_radio_height"], 1)
        self.assertEqual(fields[2]["_screen_y"], fields[3]["_screen_y"])
        self.assertLess(fields[2]["_label_x"], fields[3]["_label_x"])

    def test_form_text_edit_inserts_at_cursor(self):
        class FakeScreen:
            def __init__(self):
                self.keys = [10, 10]

            def clear(self):
                pass

            def border(self, *args):
                pass

            def addstr(self, *args):
                pass

            def refresh(self):
                pass

            def touchwin(self):
                pass

            def getch(self):
                if self.keys:
                    return self.keys.pop(0)
                return 27

            def getmaxyx(self):
                return (24, 80)

        class FakeEditWindow:
            def __init__(self):
                self.keys = [curses.KEY_LEFT, "X", "\n"]

            def bkgd(self, *args):
                pass

            def keypad(self, *args):
                pass

            def clear(self):
                pass

            def addstr(self, *args):
                pass

            def move(self, *args):
                pass

            def refresh(self):
                pass

            def get_wch(self):
                if self.keys:
                    return self.keys.pop(0)
                return "\n"

        tui = object.__new__(Tui)
        tui.screen = FakeScreen()
        tui.restore_screen = lambda: None
        tui.COLOR_HIGHLIGHT = 0
        tui.COLOR_STATUS = 0
        tui.COLOR_WARNING = 0
        edit_window = FakeEditWindow()
        old_newwin = tui_module.curses.newwin
        old_curs_set = tui_module.curses.curs_set
        tui_module.curses.newwin = lambda *args: edit_window
        tui_module.curses.curs_set = lambda *args: None
        try:
            result = Tui._run_form_loop(
                tui,
                [
                    {
                        "label": i18n.get("name"),
                        "type": "text",
                        "name": "name",
                        "required": True,
                        "value": "abc",
                    },
                    {"label": i18n.get("save"), "type": "button"},
                ],
                "Test",
            )
        finally:
            tui_module.curses.newwin = old_newwin
            tui_module.curses.curs_set = old_curs_set

        self.assertEqual(result["name"], "abXc")

    def test_restore_screen_clears_and_restores_terminal_once(self):
        class FakeScreen:
            def __init__(self):
                self.calls = []

            def keypad(self, value):
                self.calls.append(("keypad", value))

            def clear(self):
                self.calls.append(("clear",))

            def refresh(self):
                self.calls.append(("refresh",))

        calls = []
        old_curs_set = tui_module.curses.curs_set
        old_nocbreak = tui_module.curses.nocbreak
        old_echo = tui_module.curses.echo
        old_endwin = tui_module.curses.endwin
        tui_module.curses.curs_set = lambda value: calls.append(("curs_set", value))
        tui_module.curses.nocbreak = lambda: calls.append(("nocbreak",))
        tui_module.curses.echo = lambda: calls.append(("echo",))
        tui_module.curses.endwin = lambda: calls.append(("endwin",))
        try:
            tui = object.__new__(Tui)
            tui.screen = FakeScreen()
            tui._screen_restored = False
            tui._alternate_screen_supported = False
            tui.screen_policy = "isolated"

            Tui.restore_screen(tui)
            Tui.restore_screen(tui)
        finally:
            tui_module.curses.curs_set = old_curs_set
            tui_module.curses.nocbreak = old_nocbreak
            tui_module.curses.echo = old_echo
            tui_module.curses.endwin = old_endwin

        self.assertEqual(
            tui.screen.calls,
            [("keypad", 0), ("clear",), ("refresh",)],
        )
        self.assertEqual(
            calls,
            [("curs_set", 1), ("nocbreak",), ("echo",), ("endwin",)],
        )

    def test_restore_screen_preserves_alternate_screen_until_endwin(self):
        class FakeScreen:
            def __init__(self):
                self.calls = []

            def keypad(self, value):
                self.calls.append(("keypad", value))

            def clear(self):
                self.calls.append(("clear",))

            def refresh(self):
                self.calls.append(("refresh",))

        calls = []
        old_curs_set = tui_module.curses.curs_set
        old_nocbreak = tui_module.curses.nocbreak
        old_echo = tui_module.curses.echo
        old_endwin = tui_module.curses.endwin
        tui_module.curses.curs_set = lambda value: calls.append(("curs_set", value))
        tui_module.curses.nocbreak = lambda: calls.append(("nocbreak",))
        tui_module.curses.echo = lambda: calls.append(("echo",))
        tui_module.curses.endwin = lambda: calls.append(("endwin",))
        try:
            tui = object.__new__(Tui)
            tui.screen = FakeScreen()
            tui._screen_restored = False
            tui._alternate_screen_supported = True
            tui.screen_policy = "isolated"

            Tui.restore_screen(tui)
        finally:
            tui_module.curses.curs_set = old_curs_set
            tui_module.curses.nocbreak = old_nocbreak
            tui_module.curses.echo = old_echo
            tui_module.curses.endwin = old_endwin

        self.assertEqual(tui.screen.calls, [("keypad", 0)])
        self.assertEqual(
            calls,
            [("curs_set", 1), ("nocbreak",), ("echo",), ("endwin",)],
        )

    def test_restore_screen_private_policy_clears_scrollback_after_endwin(self):
        class FakeScreen:
            def __init__(self):
                self.calls = []

            def keypad(self, value):
                self.calls.append(("keypad", value))

            def clear(self):
                self.calls.append(("clear",))

            def refresh(self):
                self.calls.append(("refresh",))

        calls = []
        stdout = StringIO()
        old_stdout = tui_module.sys.stdout
        old_curs_set = tui_module.curses.curs_set
        old_nocbreak = tui_module.curses.nocbreak
        old_echo = tui_module.curses.echo
        old_endwin = tui_module.curses.endwin
        tui_module.sys.stdout = stdout
        tui_module.curses.curs_set = lambda value: calls.append(("curs_set", value))
        tui_module.curses.nocbreak = lambda: calls.append(("nocbreak",))
        tui_module.curses.echo = lambda: calls.append(("echo",))
        tui_module.curses.endwin = lambda: calls.append(("endwin",))
        try:
            tui = object.__new__(Tui)
            tui.screen = FakeScreen()
            tui._screen_restored = False
            tui._alternate_screen_supported = True
            tui.screen_policy = "private"

            Tui.restore_screen(tui)
            Tui.restore_screen(tui)
        finally:
            tui_module.sys.stdout = old_stdout
            tui_module.curses.curs_set = old_curs_set
            tui_module.curses.nocbreak = old_nocbreak
            tui_module.curses.echo = old_echo
            tui_module.curses.endwin = old_endwin

        self.assertEqual(tui.screen.calls, [("keypad", 0)])
        self.assertEqual(stdout.getvalue(), "\033[H\033[2J\033[3J")
        self.assertEqual(
            calls,
            [("curs_set", 1), ("nocbreak",), ("echo",), ("endwin",)],
        )

    def test_effective_screen_policy_falls_back_for_invalid_values(self):
        class FakeManager:
            def __init__(self, policy):
                self.config = {"tui_screen_policy": policy}

        tui = object.__new__(Tui)
        for policy in ([], {}, None, "inline"):
            with self.subTest(policy=policy):
                tui.host_manager = FakeManager(policy)
                self.assertEqual(Tui._effective_screen_policy(tui), "isolated")

    def test_theme_uses_terminal_default_color_for_footer_status(self):
        class FakeManager:
            config = {"theme": {"prefix_color": "cyan"}}

        pairs = []
        old_start_color = tui_module.curses.start_color
        old_use_default_colors = tui_module.curses.use_default_colors
        old_init_pair = tui_module.curses.init_pair
        tui_module.curses.start_color = lambda: None
        tui_module.curses.use_default_colors = lambda: None
        tui_module.curses.init_pair = lambda *args: pairs.append(args)
        try:
            tui = object.__new__(Tui)
            tui.host_manager = FakeManager()

            Tui._init_theme(tui)
        finally:
            tui_module.curses.start_color = old_start_color
            tui_module.curses.use_default_colors = old_use_default_colors
            tui_module.curses.init_pair = old_init_pair

        self.assertEqual(tui.COLOR_STATUS, 0)
        self.assertIn((3, curses.COLOR_CYAN, -1), pairs)
        self.assertNotIn((4, curses.COLOR_BLACK, curses.COLOR_WHITE), pairs)

    def test_init_failure_after_initscr_restores_terminal(self):
        class FakeScreen:
            def __init__(self):
                self.calls = []

            def keypad(self, value):
                self.calls.append(("keypad", value))
                if value == 1:
                    raise RuntimeError("keypad failed")

            def clear(self):
                self.calls.append(("clear",))

            def refresh(self):
                self.calls.append(("refresh",))

            def border(self, *args):
                self.calls.append(("border", args))

        class FakeManager:
            config = {}

        screen = FakeScreen()
        calls = []
        old_initscr = tui_module.curses.initscr
        old_noecho = tui_module.curses.noecho
        old_cbreak = tui_module.curses.cbreak
        old_curs_set = tui_module.curses.curs_set
        old_nocbreak = tui_module.curses.nocbreak
        old_echo = tui_module.curses.echo
        old_endwin = tui_module.curses.endwin
        old_terminal_supports_alternate_screen = Tui.terminal_supports_alternate_screen
        tui_module.curses.initscr = lambda: screen
        tui_module.curses.noecho = lambda: calls.append(("noecho",))
        tui_module.curses.cbreak = lambda: calls.append(("cbreak",))
        tui_module.curses.curs_set = lambda value: calls.append(("curs_set", value))
        tui_module.curses.nocbreak = lambda: calls.append(("nocbreak",))
        tui_module.curses.echo = lambda: calls.append(("echo",))
        tui_module.curses.endwin = lambda: calls.append(("endwin",))
        Tui.terminal_supports_alternate_screen = staticmethod(lambda: False)
        try:
            with self.assertRaisesRegex(RuntimeError, "keypad failed"):
                Tui(FakeManager())
        finally:
            tui_module.curses.initscr = old_initscr
            tui_module.curses.noecho = old_noecho
            tui_module.curses.cbreak = old_cbreak
            tui_module.curses.curs_set = old_curs_set
            tui_module.curses.nocbreak = old_nocbreak
            tui_module.curses.echo = old_echo
            tui_module.curses.endwin = old_endwin
            Tui.terminal_supports_alternate_screen = old_terminal_supports_alternate_screen

        self.assertEqual(
            screen.calls,
            [("keypad", 1), ("keypad", 0), ("clear",), ("refresh",)],
        )
        self.assertEqual(
            calls,
            [
                ("noecho",),
                ("cbreak",),
                ("curs_set", 0),
                ("curs_set", 1),
                ("nocbreak",),
                ("echo",),
                ("endwin",),
            ],
        )

    def test_selection_screen_does_not_draw_outer_frame(self):
        class FakeScreen:
            def __init__(self):
                self.border_calls = 0
                self.messages = []

            def clear(self):
                pass

            def border(self, _):
                self.border_calls += 1

            def getmaxyx(self):
                return (24, 100)

            def addstr(self, *args):
                for arg in args:
                    if isinstance(arg, str):
                        self.messages.append(arg)

            def refresh(self):
                pass

        class FakeManager:
            config = {"show_detail_pane": True}

        tui = object.__new__(Tui)
        tui.screen = FakeScreen()
        tui.host_manager = FakeManager()
        tui.mode = "connect"
        tui.input_mode = "navigate"
        tui.search_query = ""
        tui.highlight_line_number = 0
        tui.top_line_number = 0
        tui.get_current_node = lambda: None
        tui.get_lines_with_level = lambda: []

        Tui.render_screen(tui)

        self.assertEqual(tui.screen.border_calls, 0)
        self.assertNotIn(" sshgo ", tui.screen.messages)
        self.assertTrue(any("No hosts" in message for message in tui.screen.messages))

    def test_collapse_from_child_collapses_nearest_parent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "config": {"import_ssh_config": False},
                "hosts": [
                    {
                        "type": "group",
                        "name": "group",
                        "expanded": True,
                        "children": [
                            {
                                "type": "host",
                                "name": "child",
                                "host": "child.example.com",
                                "user": "deploy",
                                "password": "pw",
                            }
                        ],
                    }
                ],
            }
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)
            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))

            tui = object.__new__(Tui)
            tui.host_manager = manager
            tui.mode = "connect"
            tui.search_query = ""
            tui.input_mode = "navigate"
            tui.highlight_line_number = 1
            tui.top_line_number = 0
            tui._recent_group = None
            tui._recent_group_ts = 0

            self.assertEqual(
                [node["name"] for node in Tui.get_lines_with_level(tui)],
                ["group", "child"],
            )
            Tui._set_expansion(tui, False)
            self.assertFalse(manager.hosts[0]["expanded"])
            self.assertEqual(tui.highlight_line_number, 0)
            self.assertEqual(
                [node["name"] for node in Tui.get_lines_with_level(tui)],
                ["group"],
            )

            Tui._set_expansion(tui, True)
            self.assertTrue(manager.hosts[0]["expanded"])
            self.assertEqual(
                [node["name"] for node in Tui.get_lines_with_level(tui)],
                ["group", "child"],
            )

    def test_enter_toggles_group_expansion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "config": {"import_ssh_config": False},
                "hosts": [
                    {
                        "type": "group",
                        "name": "group",
                        "expanded": True,
                        "children": [
                            {
                                "type": "host",
                                "name": "child",
                                "host": "child.example.com",
                                "user": "deploy",
                                "password": "pw",
                            }
                        ],
                    }
                ],
            }
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)
            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))

            tui = object.__new__(Tui)
            tui.host_manager = manager
            tui.mode = "connect"
            tui.search_query = ""
            tui.input_mode = "navigate"
            tui.highlight_line_number = 0
            tui.top_line_number = 0
            tui._recent_group = None
            tui._recent_group_ts = 0

            Tui.handle_enter(tui)
            self.assertFalse(manager.hosts[0]["expanded"])
            self.assertEqual(
                [node["name"] for node in Tui.get_lines_with_level(tui)],
                ["group"],
            )

            Tui.handle_enter(tui)
            self.assertTrue(manager.hosts[0]["expanded"])
            self.assertEqual(
                [node["name"] for node in Tui.get_lines_with_level(tui)],
                ["group", "child"],
            )

    def test_enter_on_host_still_connects(self):
        node = {"type": "host", "name": "host"}
        tui = object.__new__(Tui)
        tui.mode = "connect"
        tui.get_current_node = lambda: node
        connected = []
        tui.connect_to_node = lambda selected: connected.append(selected)

        Tui.handle_enter(tui)

        self.assertEqual(connected, [node])

    def test_enter_in_select_modes_returns_group_without_toggling(self):
        for mode in ("select", "select_parent"):
            with self.subTest(mode=mode):
                node = {
                    "type": "group",
                    "name": "group",
                    "expanded": True,
                    "children": [{"type": "host", "name": "child"}],
                }
                tui = object.__new__(Tui)
                tui.mode = mode
                tui.get_current_node = lambda: node
                tui._set_expansion = lambda expand: self.fail(
                    f"{mode} mode must not toggle"
                )

                result = Tui.handle_enter(tui)

                self.assertIs(result, node)
                self.assertTrue(node["expanded"])

    def test_enter_on_empty_group_keeps_add_prompt(self):
        node = {"type": "group", "name": "empty", "expanded": True, "children": []}

        tui = object.__new__(Tui)
        tui.mode = "connect"
        tui.host_manager = object()
        tui.get_current_node = lambda: node
        prompts = []

        def fake_form_loop(fields, title):
            prompts.append((fields, title))
            return {"confirm": False}

        tui._run_form_loop = fake_form_loop

        Tui.handle_enter(tui)

        self.assertEqual(len(prompts), 1)
        self.assertIn("empty", prompts[0][1])

    def test_run_maps_direction_keys_to_expansion(self):
        class FakeScreen:
            def __init__(self, keys):
                self.keys = list(keys)

            def getch(self):
                return self.keys.pop(0)

        tui = object.__new__(Tui)
        tui.screen = FakeScreen([curses.KEY_LEFT, curses.KEY_RIGHT, ord("q")])
        tui.mode = "connect"
        tui.input_mode = "navigate"
        tui.search_query = ""
        tui.exit_reason = None
        calls = []
        tui.render_screen = lambda: None
        tui._set_expansion = lambda expand: calls.append(expand)

        Tui.run(tui)

        self.assertEqual(calls, [False, True])


    def test_tui_add_flow_shows_validation_error_before_save(self):
        class FakeScreen:
            def __init__(self):
                self.messages = []

            def clear(self):
                pass

            def addstr(self, *args):
                for arg in args:
                    if isinstance(arg, str):
                        self.messages.append(arg)

            def refresh(self):
                pass

            def getch(self):
                return 0

            def getmaxyx(self):
                return (24, 80)

        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            screen = FakeScreen()
            responses = [
                {"type": "host"},
                {
                    "name": "bad-port",
                    "host": "bad.example.com",
                    "port": "70000",
                    "user": "deploy",
                    "auth": "password",
                    "password": "pw",
                    "id_file": "",
                    "mfa_secret": "",
                    "proxy_command": "",
                    "ssh_jump_mode": "default",
                    "transfer_jump_mode": "default",
                },
            ]

            tui = object.__new__(Tui)
            tui.mode = "connect"
            tui.host_manager = manager
            tui.screen = screen
            tui.restore_screen = lambda: None
            tui._run_form_loop = lambda fields, title="", **kwargs: responses.pop(0)

            tui_flows.run_add_flow(
                tui,
                preselected_parent={"type": "system", "name": "Top Level"},
            )

            with open(manager.json_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual([host["name"] for host in saved["hosts"]], ["jump"])
            self.assertIn("Port '70000'", "\n".join(screen.messages))

    def test_tui_edit_preserves_raw_placeholder_host(self):
        class FakeScreen:
            def clear(self):
                pass

            def addstr(self, *args):
                pass

            def refresh(self):
                pass

            def getch(self):
                return 0

        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "config": {
                    "import_ssh_config": False,
                    "placeholders": {"domain": "example.com"},
                },
                "hosts": [
                    {
                        "type": "host",
                        "name": "templated",
                        "host": "app.{{domain}}",
                        "port": "2222",
                        "user": "deploy",
                        "password": "pw",
                    }
                ],
            }
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)
            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))

            tui = object.__new__(Tui)
            tui.host_manager = manager
            tui.screen = FakeScreen()
            tui.restore_screen = lambda: None
            tui._recent_group = None
            tui._recent_group_ts = 0
            tui.get_current_node = lambda: manager.find_host_by_alias("templated")
            tui._run_form_loop = lambda fields, title="", **kwargs: {
                "name": "templated",
                "host": "app.{{domain}}",
                "port": "2222",
                "user": "deploy",
                "auth": "password",
                "password": "pw",
                "id_file": "",
                "mfa_secret": "",
                "proxy_command": "",
                "ssh_jump_mode": "default",
                "transfer_jump_mode": "default",
            }

            tui_flows.run_edit_flow(tui)

            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["hosts"][0]["host"], "app.{{domain}}")
            self.assertEqual(saved["hosts"][0]["port"], "2222")

    def test_tui_edit_hides_proxy_command_for_nested_target(self):
        class FakeScreen:
            def clear(self):
                pass

            def addstr(self, *args):
                pass

            def refresh(self):
                pass

            def getch(self):
                return 0

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
            field_names = []

            def fake_form(fields, title="", **kwargs):
                field_names.extend(
                    field["name"] for field in fields if field.get("name")
                )
                return {
                    "name": "target",
                    "host": "target.internal",
                    "port": "22",
                    "user": "targetuser",
                    "auth": "password",
                    "password": "pw",
                    "id_file": "",
                    "mfa_secret": "",
                    "ssh_jump_mode": "default",
                    "transfer_jump_mode": "default",
                }

            tui = object.__new__(Tui)
            tui.host_manager = manager
            tui.screen = FakeScreen()
            tui.restore_screen = lambda: None
            tui._recent_group = None
            tui._recent_group_ts = 0
            tui.get_current_node = lambda: manager.find_host_by_alias("target")
            tui._run_form_loop = fake_form

            tui_flows.run_edit_flow(tui)

            self.assertNotIn("proxy_command", field_names)
            target = manager.find_host_by_alias("target")
            self.assertNotIn("proxy_command", target)
            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertNotIn("proxy_command", saved["hosts"][0]["children"][0])

    def test_tui_host_form_marks_advanced_fields_collapsed_by_default(self):
        fields = tui_forms.host_form_fields(include_proxy=True, advanced_open=False)

        advanced_toggle = next(
            field for field in fields if field.get("name") == "_advanced_open"
        )
        proxy_field = next(
            field for field in fields if field.get("name") == "proxy_command"
        )
        jump_mode_field = next(
            field for field in fields if field.get("name") == "ssh_jump_mode"
        )
        self.assertFalse(advanced_toggle["value"])
        self.assertTrue(proxy_field["advanced"])
        self.assertTrue(jump_mode_field["advanced"])

    def test_tui_edit_opens_advanced_for_existing_advanced_host(self):
        class FakeScreen:
            def clear(self):
                pass

            def addstr(self, *args):
                pass

            def refresh(self):
                pass

            def getch(self):
                return 0

        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "config": {"import_ssh_config": False},
                "hosts": [
                    {
                        "type": "host",
                        "name": "advanced",
                        "host": "advanced.example.com",
                        "port": "2222",
                        "user": "deploy",
                        "password": "pw",
                        "proxy_command": "ssh bastion nc %h %p",
                    }
                ],
            }
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)
            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))
            captured = {}

            def fake_form(fields, title="", **kwargs):
                captured["fields"] = fields
                return None

            tui = object.__new__(Tui)
            tui.host_manager = manager
            tui.screen = FakeScreen()
            tui.restore_screen = lambda: None
            tui._recent_group = None
            tui._recent_group_ts = 0
            tui.get_current_node = lambda: manager.find_host_by_alias("advanced")
            tui._run_form_loop = fake_form

            tui_flows.run_edit_flow(tui)

            advanced_toggle = next(
                field
                for field in captured["fields"]
                if field.get("name") == "_advanced_open"
            )
            self.assertTrue(advanced_toggle["value"])

    def test_tui_edit_updates_selected_node_by_id(self):
        selected = {
            "id": "selected-id",
            "type": "group",
            "name": "old-name",
            "children": [],
        }
        calls = []

        class FakeManager:
            def find_node_and_parent(self, name):
                calls.append(("find_by_name", name))
                return None, None, -1

            def validate_update_candidate_by_id(self, node_id, data):
                calls.append(("validate_by_id", node_id, dict(data)))
                return []

            def validate_update_candidate(self, name, data):
                calls.append(("validate_by_name", name, dict(data)))
                return ["should not use name validation"]

            def update_node_by_id(self, node_id, data):
                calls.append(("update_by_id", node_id, dict(data)))
                return True

            def update_node(self, name, data):
                calls.append(("update_by_name", name, dict(data)))
                return True

        tui = object.__new__(Tui)
        tui.host_manager = FakeManager()
        tui.get_current_node = lambda: selected
        tui._run_form_loop = lambda fields, title="", **kwargs: {
            "name": "new-name",
        }
        tui._show_message = lambda title, message: None
        tui._recent_group = None
        tui._recent_group_ts = 0

        tui_flows.run_edit_flow(tui)

        self.assertIn(("validate_by_id", "selected-id", {"name": "new-name"}), calls)
        self.assertIn(("update_by_id", "selected-id", {"name": "new-name"}), calls)
        self.assertFalse(any(call[0] == "update_by_name" for call in calls))

    def test_tui_add_flow_uses_preselected_parent_id(self):
        parent = {
            "id": "parent-id",
            "type": "group",
            "name": "parent",
            "children": [],
        }
        calls = []
        responses = iter([
            {"type": "group"},
            {"name": "child"},
        ])

        class FakeManager:
            def find_node_and_parent(self, name):
                calls.append(("find_by_name", name))
                return None, None, -1

            def validate_add_candidate_by_parent_id(self, node, parent_id):
                calls.append(("validate_by_parent_id", node["name"], parent_id))
                return []

            def validate_add_candidate(self, node, parent_name=None):
                calls.append(("validate_by_parent_name", node["name"], parent_name))
                return ["should not use parent name validation"]

            def add_node_to_parent_id(self, node, parent_id):
                calls.append(("add_by_parent_id", node["name"], parent_id))
                return True

            def add_node(self, node, parent_name=None):
                calls.append(("add_by_parent_name", node["name"], parent_name))
                return True

        tui = object.__new__(Tui)
        tui.host_manager = FakeManager()
        tui.mode = "connect"
        tui._run_form_loop = lambda fields, title="", **kwargs: next(responses)
        tui._show_message = lambda title, message: None

        tui_flows.run_add_flow(tui, preselected_parent=parent)

        self.assertIn(("validate_by_parent_id", "child", "parent-id"), calls)
        self.assertIn(("add_by_parent_id", "child", "parent-id"), calls)
        self.assertFalse(any(call[0] == "add_by_parent_name" for call in calls))

    def test_tui_parent_select_lines_only_include_editable_saved_nodes(self):
        hosts = [
            {
                "id": "saved-group-id",
                "type": "group",
                "name": "saved-group",
                "expanded": True,
                "children": [
                    {
                        "id": "saved-child-id",
                        "type": "host",
                        "name": "saved-child",
                        "host": "saved-child.example.com",
                        "user": "deploy",
                    }
                ],
            },
            {
                "type": "group",
                "name": "imported",
                "source": "ssh_config_group",
                "expanded": True,
                "children": [
                    {
                        "type": "host",
                        "name": "imported-host",
                        "source": "ssh_config",
                    }
                ],
            },
            {
                "id": "saved-host-id",
                "type": "host",
                "name": "saved-host",
                "host": "saved-host.example.com",
                "user": "deploy",
            },
            {
                "type": "host",
                "name": "history-host",
                "source": "history",
            },
        ]

        class FakeManager:
            def get_hosts(self):
                return hosts

        tui = object.__new__(Tui)
        tui.host_manager = FakeManager()
        tui.mode = "select_parent"
        tui.search_query = ""

        names = [line["name"] for line in Tui.get_lines_with_level(tui)]

        self.assertEqual(
            names,
            ["[Top Level]", "saved-group", "saved-child", "saved-host"],
        )

    def test_tui_add_flow_rejects_readonly_preselected_parent(self):
        calls = []

        tui = object.__new__(Tui)
        tui.mode = "connect"
        tui._show_message = lambda title, message: calls.append("readonly")

        def fail_form(*args, **kwargs):
            raise AssertionError("form should not open for read-only parent")

        tui._run_form_loop = fail_form

        tui_flows.run_add_flow(
            tui,
            preselected_parent={
                "type": "host",
                "name": "recent-host",
                "source": "history",
            },
        )

        self.assertEqual(calls, ["readonly"])

    def test_tui_form_validation_stays_in_form_and_preserves_value(self):
        class FakeScreen:
            def __init__(self):
                self.keys = [9, 10, 27]
                self.messages = []

            def clear(self):
                pass

            def border(self, *args):
                pass

            def addstr(self, *args):
                for arg in args:
                    if isinstance(arg, str):
                        self.messages.append(arg)

            def refresh(self):
                pass

            def getch(self):
                if self.keys:
                    return self.keys.pop(0)
                return 27

            def getmaxyx(self):
                return (24, 80)

        tui = object.__new__(Tui)
        tui.screen = FakeScreen()
        calls = []
        fields = [
            {
                "label": i18n.get("name"),
                "type": "text",
                "name": "name",
                "required": True,
                "value": "bad",
            },
            {"label": i18n.get("save"), "type": "button"},
            {"label": i18n.get("cancel"), "type": "button", "name": "cancel"},
        ]

        def validator(form_data):
            calls.append(dict(form_data))
            return (["Duplicate node name: bad"], "name")

        result = Tui._run_form_loop(
            tui,
            fields,
            i18n.get("edit_group", name="bad"),
            validator=validator,
        )

        self.assertIsNone(result)
        self.assertEqual(calls[0]["name"], "bad")
        self.assertEqual(fields[0]["value"], "bad")
        self.assertIn("Duplicate node name: bad", "\n".join(tui.screen.messages))

    def test_tui_delete_defaults_to_cancel_and_shows_impact(self):
        class FakeScreen:
            def clear(self):
                pass

            def addstr(self, *args):
                pass

            def refresh(self):
                pass

            def getch(self):
                return 0

        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
            captured = {}

            def fake_form(fields, title="", **kwargs):
                captured["fields"] = fields
                captured["kwargs"] = kwargs
                return None

            tui = object.__new__(Tui)
            tui.host_manager = manager
            tui.screen = FakeScreen()
            tui.get_current_node = lambda: manager.find_host_by_alias("target")
            tui._run_form_loop = fake_form

            tui_flows.run_delete_flow(tui)

            labels = [field["label"] for field in captured["fields"]]
            self.assertEqual(captured["kwargs"]["initial_focus_name"], "cancel")
            self.assertIn(i18n.get("delete"), labels)
            self.assertTrue(
                any("targetuser@target.internal:2222" in label for label in labels)
            )

    def test_tui_delete_removes_selected_node_by_id(self):
        selected = {
            "id": "selected-id",
            "type": "group",
            "name": "group",
            "children": [],
        }
        calls = []

        class FakeManager:
            def delete_node_by_id(self, node_id):
                calls.append(("delete_by_id", node_id))
                return True

            def delete_host(self, name):
                calls.append(("delete_by_name", name))
                return True

        tui = object.__new__(Tui)
        tui.host_manager = FakeManager()
        tui.get_current_node = lambda: selected
        tui._run_form_loop = lambda fields, title="", **kwargs: {"confirm": True}
        tui.highlight_line_number = 1

        tui_flows.run_delete_flow(tui)

        self.assertEqual(calls, [("delete_by_id", "selected-id")])
        self.assertEqual(tui.highlight_line_number, 0)

if __name__ == "__main__":
    unittest.main()
