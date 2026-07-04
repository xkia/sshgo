import curses
import json
import os
import tempfile
import unittest

import tui as tui_module
from host_manager import HostManager
from i18n import i18n
from tui import Tui


class TuiTests(unittest.TestCase):
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
        tui = object.__new__(Tui)
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

        layout = Tui._layout_form_fields(tui, fields, 100, start_y=2)

        self.assertGreaterEqual(layout["input_width"], 18)
        self.assertEqual(fields[0]["_screen_y"], 2)
        self.assertNotEqual(fields[0]["_label_x"], 99)
        self.assertGreater(fields[1]["_radio_height"], 1)
        self.assertEqual(fields[2]["_screen_y"], fields[3]["_screen_y"])
        self.assertLess(fields[2]["_label_x"], fields[3]["_label_x"])

    def test_text_edit_key_supports_cursor_clear_delete_and_paste(self):
        tui = object.__new__(Tui)

        value, cursor, action = Tui._apply_text_edit_key(
            tui,
            "abc",
            3,
            curses.KEY_LEFT,
        )
        self.assertEqual((value, cursor, action), ("abc", 2, None))

        value, cursor, action = Tui._apply_text_edit_key(tui, value, cursor, "X")
        self.assertEqual((value, cursor, action), ("abXc", 3, None))

        value, cursor, action = Tui._apply_text_edit_key(tui, value, cursor, "\x01")
        self.assertEqual((value, cursor, action), ("abXc", 0, None))

        value, cursor, action = Tui._apply_text_edit_key(tui, value, cursor, ">")
        self.assertEqual((value, cursor, action), (">abXc", 1, None))

        value, cursor, action = Tui._apply_text_edit_key(tui, value, cursor, "\x05")
        self.assertEqual((value, cursor, action), (">abXc", 5, None))

        value, cursor, action = Tui._apply_text_edit_key(
            tui,
            value,
            cursor,
            curses.KEY_BACKSPACE,
        )
        self.assertEqual((value, cursor, action), (">abX", 4, None))

        value, cursor, action = Tui._apply_text_edit_key(
            tui,
            "abcd",
            2,
            curses.KEY_DC,
        )
        self.assertEqual((value, cursor, action), ("abd", 2, None))

        value, cursor, action = Tui._apply_text_edit_key(tui, "ab", 1, "xy")
        self.assertEqual((value, cursor, action), ("axyb", 3, None))

        value, cursor, action = Tui._apply_text_edit_key(tui, value, cursor, "\x15")
        self.assertEqual((value, cursor, action), ("", 0, None))

        self.assertEqual(
            Tui._apply_text_edit_key(tui, "done", 4, "\n")[2],
            "commit",
        )
        self.assertEqual(
            Tui._apply_text_edit_key(tui, "done", 4, 27)[2],
            "cancel",
        )

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
        tui_module.curses.initscr = lambda: screen
        tui_module.curses.noecho = lambda: calls.append(("noecho",))
        tui_module.curses.cbreak = lambda: calls.append(("cbreak",))
        tui_module.curses.curs_set = lambda value: calls.append(("curs_set", value))
        tui_module.curses.nocbreak = lambda: calls.append(("nocbreak",))
        tui_module.curses.echo = lambda: calls.append(("echo",))
        tui_module.curses.endwin = lambda: calls.append(("endwin",))
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

    def test_main_split_layout_reserves_detail_pane_width(self):
        class FakeManager:
            config = {"show_detail_pane": True}

        tui = object.__new__(Tui)
        tui.host_manager = FakeManager()
        host_node = {"type": "host", "name": "demo"}

        wide = Tui._main_split_layout(tui, 120, host_node)
        self.assertIsNotNone(wide["detail_x"])
        self.assertGreaterEqual(wide["detail_width"], 34)
        self.assertGreaterEqual(wide["list_width"], 24)
        self.assertEqual(wide["separator_x"], wide["detail_x"] - 1)

        narrow = Tui._main_split_layout(tui, 80, host_node)
        self.assertIsNone(narrow["detail_x"])

        tui.host_manager.config["show_detail_pane"] = False
        disabled = Tui._main_split_layout(tui, 120, host_node)
        self.assertIsNone(disabled["detail_x"])

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

        class FakeManager:
            def contains_hosts(self, selected):
                self.selected = selected
                return False

        manager = FakeManager()
        tui = object.__new__(Tui)
        tui.mode = "connect"
        tui.host_manager = manager
        tui.get_current_node = lambda: node
        prompts = []

        def fake_form_loop(fields, title):
            prompts.append((fields, title))
            return {"confirm": False}

        tui._run_form_loop = fake_form_loop
        tui.run_add_flow = lambda preselected_parent=None: self.fail(
            "cancelled prompt must not add"
        )

        Tui.handle_enter(tui)

        self.assertIs(manager.selected, node)
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


    def test_recent_group_uses_current_name_after_rename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
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
                    "host": "target.internal:2222",
                    "user": "targetuser",
                },
            )

            tui = object.__new__(Tui)
            tui.host_manager = manager
            tui._recent_group = None
            tui._recent_group_ts = 0

            recent_group = Tui._build_recent_group(tui)
            recent_names = [
                child["name"] for child in recent_group.get("children", [])
            ]
            self.assertIn("renamed-target", recent_names)
            self.assertNotIn("target", recent_names)

    def test_recent_group_is_collapsed_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
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

            recent_group = Tui._build_recent_group(tui)
            self.assertFalse(recent_group.get("expanded"))

    def test_recent_group_is_hidden_when_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(temp_dir)
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

    def test_recent_group_resolves_by_node_id_before_endpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "config": {"import_ssh_config": False},
                "hosts": [
                    {
                        "type": "host",
                        "name": "app-22",
                        "host": "shared.internal:22",
                        "user": "deploy",
                        "password": "pw",
                    },
                    {
                        "type": "host",
                        "name": "app-2222",
                        "host": "shared.internal:2222",
                        "user": "deploy",
                        "password": "pw",
                    },
                ],
            }
            path = os.path.join(temp_dir, "hosts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)

            manager = HostManager(path, data_dir=os.path.join(temp_dir, "data"))
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
                    "host": "shared.internal:2222",
                    "user": "deploy",
                },
            )

            tui = object.__new__(Tui)
            tui.host_manager = manager
            tui._recent_group = None
            tui._recent_group_ts = 0

            recent_group = Tui._build_recent_group(tui)
            recent_names = [
                child["name"] for child in recent_group.get("children", [])
            ]
            self.assertEqual(recent_names, ["renamed-app"])

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

            Tui.run_add_flow(
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
                        "host": "app.{{domain}}:2222",
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

            Tui.run_edit_flow(tui)

            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["hosts"][0]["host"], "app.{{domain}}:2222")

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
                                "host": "target.internal:22",
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

            Tui.run_edit_flow(tui)

            self.assertNotIn("proxy_command", field_names)
            target = manager.find_host_by_alias("target")
            self.assertNotIn("proxy_command", target)
            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertNotIn("proxy_command", saved["hosts"][0]["children"][0])

    def test_tui_host_form_marks_advanced_fields_collapsed_by_default(self):
        tui = object.__new__(Tui)

        fields = Tui._host_form_fields(tui, include_proxy=True, advanced_open=False)

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
                        "host": "advanced.example.com:2222",
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

            Tui.run_edit_flow(tui)

            advanced_toggle = next(
                field
                for field in captured["fields"]
                if field.get("name") == "_advanced_open"
            )
            self.assertTrue(advanced_toggle["value"])

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

            Tui.run_delete_flow(tui)

            labels = [field["label"] for field in captured["fields"]]
            self.assertEqual(captured["kwargs"]["initial_focus_name"], "cancel")
            self.assertIn(i18n.get("delete"), labels)
            self.assertTrue(
                any("targetuser@target.internal:2222" in label for label in labels)
            )

if __name__ == "__main__":
    unittest.main()
