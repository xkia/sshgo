#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import curses
import getpass
import textwrap
import curses.textpad as textpad

from host_manager import HostManager
from i18n import i18n

_AUTO_GENERATED_SOURCES = frozenset({"ssh_config_group", "recent_group"})
_READONLY_SOURCES = frozenset({"ssh_config", "history"})


class Tui:
    def __init__(self, host_manager, mode="connect"):
        self.host_manager = host_manager
        self.mode = mode
        self.exit_reason = None
        self.screen = curses.initscr()
        curses.noecho()
        curses.cbreak()
        curses.curs_set(0)
        self.screen.keypad(1)
        self.screen.border(0)
        self.top_line_number = 0
        self.highlight_line_number = 0
        self.detail_win = None
        self.screen_size = None
        self._recent_group = None
        self._recent_group_ts = 0

        # --- Theme and Color Initialization ---
        self.COLOR_MAP = {
            "black": curses.COLOR_BLACK,
            "red": curses.COLOR_RED,
            "green": curses.COLOR_GREEN,
            "yellow": curses.COLOR_YELLOW,
            "blue": curses.COLOR_BLUE,
            "magenta": curses.COLOR_MAGENTA,
            "cyan": curses.COLOR_CYAN,
            "white": curses.COLOR_WHITE,
            "default": -1,
        }
        DEFAULT_THEME = {
            "highlight_fg": "white",
            "highlight_bg": "blue",
            "prefix_color": "red",
        }
        user_theme = self.host_manager.config.get("theme", {})
        theme = DEFAULT_THEME.copy()
        theme.update(user_theme)

        curses.start_color()
        curses.use_default_colors()

        # Pair 2: Highlight color
        hl_fg = self.COLOR_MAP.get(theme["highlight_fg"], -1)
        hl_bg = self.COLOR_MAP.get(theme["highlight_bg"], -1)
        curses.init_pair(2, hl_fg, hl_bg)
        self.COLOR_HIGHLIGHT = 2

        # Pair 3: Prefix color
        prefix_fg = self.COLOR_MAP.get(theme["prefix_color"], -1)
        curses.init_pair(3, prefix_fg, -1)
        self.COLOR_RED = 3  # Retaining name for compatibility

        self.search_query = ""
        self.input_mode = "navigate"  # Modes: navigate, search

    def __del__(self):
        self.restore_screen()

    def _set_expansion(self, expand: bool):
        node = self.get_current_node()
        if node and node.get("children") is not None:
            node["expanded"] = expand
            if node.get("source") == "recent_group":
                self.host_manager.config["recent_expanded"] = expand
                self.host_manager._save_hosts()
                self._recent_group = None  # invalidate cache

    def run(self):
        try:
            while True:
                self.render_screen()
                c = self.screen.getch()

                # --- Key Handling --- #

                # 1. Universal Cancel / Go Back (ESC)
                if c == 27:
                    if self.input_mode == "search":
                        self.input_mode = "navigate"
                        self.search_query = ""
                        self.highlight_line_number = 0
                    elif self.mode in ["select", "select_parent"]:
                        return None  # Cancel from sub-flow
                    else:
                        pass  # Do nothing in main navigation mode
                    continue

                # 2. Universal Quit (q)
                if c == ord("q"):
                    if self.input_mode == "search":
                        self.input_mode = "navigate"
                        self.search_query = ""
                    elif self.mode in ["select", "select_parent"]:
                        return None  # Cancel from sub-flow
                    else:
                        break  # Quit from main navigation mode
                    continue

                # 3. Navigation and Selection
                if c == curses.KEY_UP or c == ord("k"):
                    self.updown(-1)
                elif c == curses.KEY_DOWN or c == ord("j"):
                    self.updown(1)
                elif c == curses.KEY_ENTER or c == 10 or c == 13:
                    result = self.handle_enter()
                    if self.exit_reason == "connected":
                        return
                    if self.mode in ["select", "select_parent"]:
                        return result

                # 4. Mode-Specific Actions
                elif self.input_mode == "navigate":
                    if c == ord("l"):
                        self._set_expansion(True)
                    elif c == ord("h"):
                        self._set_expansion(False)
                    elif c == ord("f"):
                        self.input_mode = "search"
                    elif c == ord("a"):
                        self.run_add_flow()
                    elif c == ord("e"):
                        self.run_edit_flow()
                    elif c == ord("d"):
                        self.run_delete_flow()

                elif self.input_mode == "search":
                    if c == curses.KEY_BACKSPACE or c == 127:
                        self.search_query = self.search_query[:-1]
                        self.highlight_line_number = 0
                    elif c == 21:  # Ctrl+U
                        self.search_query = ""
                        self.highlight_line_number = 0
                    elif 32 <= c <= 126:
                        self.search_query += chr(c)
                        self.highlight_line_number = 0

        except KeyboardInterrupt:
            return  # Graceful exit on Ctrl+C

    def _draw_form(
        self, visible_fields, active_field_index, title="", error_message=""
    ):
        self.screen.clear()
        self.screen.border(0)  # Draws border around the entire screen

        # Calculate max label length for alignment
        max_label_len = 0
        if visible_fields:
            # Exclude static_text fields from label alignment calculation
            max_label_len = max(
                len(f.get("label", ""))
                for f in visible_fields
                if f.get("type") != "static_text"
            )

        input_start_x = 2 + max_label_len + 2  # Start after label and 2 spaces

        # Determine the bounding box of the form fields
        min_y_content = 3
        max_y_content = (
            max(f["y"] for f in visible_fields) if visible_fields else min_y_content
        )

        # Box dimensions
        box_top_y = min_y_content - 1
        box_left_x = 1
        box_bottom_y = max_y_content + 2  # +2 for padding and bottom border
        box_right_x = (
            input_start_x + 22 + 1
        )  # Input box width (20) + 2 spaces + 1 for right border

        # Draw the inner box
        self.screen.addstr(
            box_top_y, box_left_x, "+" + "-" * (box_right_x - box_left_x - 2) + "+"
        )
        for y_coord in range(box_top_y + 1, box_bottom_y):
            self.screen.addstr(y_coord, box_left_x, "|")
            self.screen.addstr(y_coord, box_right_x - 1, "|")
        self.screen.addstr(
            box_bottom_y, box_left_x, "+" + "-" * (box_right_x - box_left_x - 2) + "+"
        )

        if title:
            self.screen.addstr(
                1, 2, title, curses.A_BOLD
            )  # Title remains outside the box

        if error_message:
            self.screen.addstr(
                box_bottom_y + 1,
                box_left_x + 2,
                error_message,
                curses.color_pair(self.COLOR_RED),
            )

        for i, field in enumerate(visible_fields):
            y, x = field["y"], field["x"]
            label = field.get("label", "")

            attr = curses.A_REVERSE if i == active_field_index else curses.A_NORMAL

            if field["type"] == "static_text":
                self.screen.addstr(y, x, label)
                continue  # Skip the rest of the drawing logic for this field type

            if i == active_field_index:
                self.screen.addstr(y, x - 2, ">", curses.A_BOLD)  # Add a marker

            self.screen.addstr(y, x, label)

            if field["type"] in ["text", "password"]:
                value = field.get("value") or ""
                display_value = (
                    "*" * len(value) if field["type"] == "password" else value
                )
                self.screen.addstr(y, input_start_x, f" {display_value:<20} ", attr)

            elif field["type"] == "radio":
                value = field.get("value")
                for j, option in enumerate(field["options"]):
                    display_option = i18n.get(option)
                    option_attr = (
                        curses.A_BOLD if i == active_field_index else curses.A_NORMAL
                    )
                    marker = "(•)" if value == option else "( )"
                    if value == option:
                        option_attr |= curses.A_REVERSE
                    self.screen.addstr(
                        y + j, input_start_x, f"{marker} {display_option}", option_attr
                    )

            elif field["type"] == "button":
                self.screen.addstr(y, x, f"[ {label} ]", attr)

        # Footer setup for context-sensitive hints
        footer_line = self.screen.getmaxyx()[0] - 1
        if footer_line > 0:
            hint_text = ""
            if active_field_index < len(visible_fields):
                current_field = visible_fields[active_field_index]
                if current_field["type"] in ("text", "password"):
                    hint_text = i18n.get("footer_form_text")
                elif current_field["type"] == "radio":
                    hint_text = i18n.get("footer_form_radio")
                elif (
                    current_field["type"] == "button"
                    or current_field["type"] == "static_text"
                ):
                    hint_text = i18n.get("footer_form_button")
            else:
                hint_text = i18n.get("footer_form_cancel")

            self.screen.attron(curses.A_REVERSE)
            self.screen.addstr(footer_line, 0, " " * (self.screen.getmaxyx()[1] - 1))
            self.screen.addstr(footer_line, 1, hint_text)
            self.screen.attroff(curses.A_REVERSE)

        self.screen.refresh()

    def _run_form_loop(self, fields, title=""):
        active_field_index = 0
        form_data = {}
        for field in fields:
            if field.get("name"):
                form_data[field["name"]] = field.get("value")

        error_message = ""

        while True:
            # Dynamically adjust field visibility based on other field values
            auth_method = form_data.get("auth")
            if auth_method:
                for field in fields:
                    if field.get("name") == "password":
                        field["visible"] = auth_method == "password"
                        field["required"] = auth_method == "password"
                    elif field.get("name") == "id_file":
                        field["visible"] = auth_method == "key"
                        field["required"] = auth_method == "key"

            visible_fields = [f for f in fields if f.get("visible", True)]

            for field in visible_fields:
                if field.get("name") in form_data:
                    field["value"] = form_data.get(field["name"])

            if not visible_fields:
                return None

            # Filter out non-interactive fields for indexing
            interactive_fields = [
                f for f in visible_fields if f.get("type") != "static_text"
            ]
            if not interactive_fields:
                # If no interactive fields, wait for Esc or q to exit
                self._draw_form(visible_fields, -1, title, error_message)
                c = self.screen.getch()
                if c in [27, ord("q")]:
                    return None
                continue

            if active_field_index >= len(interactive_fields):
                active_field_index = len(interactive_fields) - 1

            # Find the index of the active field in the full visible_fields list
            full_index = visible_fields.index(interactive_fields[active_field_index])

            self._draw_form(visible_fields, full_index, title, error_message)
            c = self.screen.getch()
            error_message = ""

            active_field = interactive_fields[active_field_index]

            if c in [curses.KEY_UP, ord("k")]:
                active_field_index = (
                    active_field_index - 1 + len(interactive_fields)
                ) % len(interactive_fields)
            elif c in [curses.KEY_DOWN, ord("j"), 9]:  # Tab
                active_field_index = (active_field_index + 1) % len(interactive_fields)
            elif c in [curses.KEY_ENTER, 10, 13]:
                field_type = active_field.get("type")

                if field_type in ["text", "password"]:
                    curses.curs_set(1)
                    max_label_len = max(
                        len(f.get("label", ""))
                        for f in visible_fields
                        if f.get("type") != "static_text"
                    )
                    input_start_x = 2 + max_label_len + 2
                    edit_win = curses.newwin(1, 21, active_field["y"], input_start_x)
                    edit_win.bkgd(" ", curses.color_pair(self.COLOR_HIGHLIGHT))
                    self.screen.refresh()
                    edit_win.keypad(True)

                    s = str(form_data.get(active_field["name"], "") or "")
                    cancelled = False

                    if active_field.get("name") == "name":
                        while True:
                            edit_win.clear()
                            display_s = s
                            while True:
                                try:
                                    edit_win.addstr(0, 0, display_s)
                                    break
                                except curses.error:
                                    display_s = display_s[1:]
                            edit_win.refresh()
                            try:
                                ch = edit_win.get_wch()
                            except curses.error:
                                continue
                            if ch == "\n" or ch == curses.KEY_ENTER:
                                break
                            elif ch == 27:
                                cancelled = True
                                break
                            elif (
                                ch == curses.KEY_BACKSPACE or ch == "\x7f" or ch == "\b"
                            ):
                                if len(s) > 0:
                                    s = s[:-1]
                            elif isinstance(ch, str) and len(ch) == 1:
                                s += ch
                    else:
                        while True:
                            display_s = s
                            if active_field["type"] == "password":
                                display_s = "*" * len(s)
                            edit_win.clear()
                            if len(display_s) >= 20:
                                display_s = display_s[-20:]
                            edit_win.addstr(0, 0, display_s)
                            edit_win.refresh()
                            ch = edit_win.getch()
                            if ch == 10 or ch == curses.KEY_ENTER:
                                break
                            elif ch == 27:
                                cancelled = True
                                break
                            elif ch == curses.KEY_BACKSPACE or ch == 127:
                                s = s[:-1]
                            elif 32 <= ch <= 126:
                                s += chr(ch)

                    curses.curs_set(0)
                    self.screen.touchwin()
                    self.screen.refresh()
                    if cancelled:
                        continue
                    form_data[active_field["name"]] = s.strip()
                    active_field_index = (active_field_index + 1) % len(
                        interactive_fields
                    )
                    continue

                elif field_type == "radio":
                    current_value = form_data.get(active_field["name"])
                    options = active_field.get("options", [])
                    if current_value in options:
                        current_option_index = options.index(current_value)
                        next_option_index = (current_option_index + 1) % len(options)
                        form_data[active_field["name"]] = options[next_option_index]

                elif field_type == "button":
                    button_label = active_field.get("label")
                    if button_label in [i18n.get("cancel"), i18n.get("no")]:
                        return None
                    if button_label == i18n.get("yes"):
                        form_data["confirm"] = True
                        return form_data
                    if button_label in [i18n.get("save"), i18n.get("continue")]:
                        if button_label == i18n.get("save"):
                            is_valid = True
                            for field in visible_fields:
                                if field.get("required") and not form_data.get(
                                    field["name"]
                                ):
                                    error_message = i18n.get(
                                        "error_field_required", field=field["label"]
                                    )
                                    is_valid = False
                                    break
                            if not is_valid:
                                continue
                        return form_data
            elif c == ord(" "):
                if active_field.get("type") == "radio":
                    current_value = form_data.get(active_field["name"])
                    options = active_field.get("options", [])
                    if current_value in options:
                        current_option_index = options.index(current_value)
                        next_option_index = (current_option_index + 1) % len(options)
                        form_data[active_field["name"]] = options[next_option_index]
            elif c in [ord("q"), 27]:
                return None

    def run_add_flow(self, preselected_parent=None):
        original_mode = self.mode
        try:
            if preselected_parent:
                parent_node = preselected_parent
            else:
                self.mode = "select_parent"
                parent_node = self.run()
                if not parent_node:
                    return

            parent_name = (
                None if parent_node.get("type") == "system" else parent_node["name"]
            )

            node_type_fields = [
                {
                    "label": i18n.get("node_type"),
                    "type": "radio",
                    "name": "type",
                    "options": ["host", "group"],
                    "value": "host",
                    "y": 3,
                    "x": 2,
                },
                {"label": i18n.get("continue"), "type": "button", "y": 6, "x": 2},
                {"label": i18n.get("cancel"), "type": "button", "y": 6, "x": 15},
            ]
            type_data = self._run_form_loop(
                node_type_fields, i18n.get("select_node_type")
            )
            if not type_data:
                return

            node_type = type_data["type"]

            if node_type == "host":
                form_fields = [
                    {
                        "label": i18n.get("name"),
                        "type": "text",
                        "name": "name",
                        "y": 3,
                        "x": 2,
                        "required": True,
                    },
                    {
                        "label": i18n.get("host_domain"),
                        "type": "text",
                        "name": "host",
                        "y": 4,
                        "x": 2,
                        "required": True,
                    },
                    {
                        "label": i18n.get("port"),
                        "type": "text",
                        "name": "port",
                        "value": "22",
                        "y": 5,
                        "x": 2,
                        "required": True,
                    },
                    {
                        "label": i18n.get("username"),
                        "type": "text",
                        "name": "user",
                        "y": 6,
                        "x": 2,
                        "required": True,
                        "value": getpass.getuser(),
                    },
                    {
                        "label": i18n.get("auth_method"),
                        "type": "radio",
                        "name": "auth",
                        "options": ["password", "key"],
                        "value": "password",
                        "y": 7,
                        "x": 2,
                    },
                    {
                        "label": i18n.get("password"),
                        "type": "password",
                        "name": "password",
                        "y": 9,
                        "x": 2,
                        "visible": True,
                        "required": True,
                    },
                    {
                        "label": i18n.get("key_path"),
                        "type": "text",
                        "name": "id_file",
                        "y": 10,
                        "x": 2,
                        "visible": False,
                        "required": False,
                    },
                    {
                        "label": i18n.get("mfa_secret"),
                        "type": "text",
                        "name": "mfa_secret",
                        "y": 11,
                        "x": 2,
                    },
                    {
                        "label": i18n.get("ssh_jump_mode"),
                        "type": "radio",
                        "name": "ssh_jump_mode",
                        "options": ["default", "shell", "tunnel"],
                        "value": "default",
                        "y": 12,
                        "x": 2,
                    },
                    {
                        "label": i18n.get("transfer_jump_mode"),
                        "type": "radio",
                        "name": "transfer_jump_mode",
                        "options": ["default", "tunnel", "relay"],
                        "value": "default",
                        "y": 15,
                        "x": 2,
                    },
                    {"label": i18n.get("save"), "type": "button", "y": 19, "x": 2},
                    {"label": i18n.get("cancel"), "type": "button", "y": 19, "x": 10},
                ]
                title = i18n.get("add_new_host")
            else:
                form_fields = [
                    {
                        "label": i18n.get("name"),
                        "type": "text",
                        "name": "name",
                        "y": 3,
                        "x": 2,
                        "required": True,
                    },
                    {"label": i18n.get("save"), "type": "button", "y": 5, "x": 2},
                    {"label": i18n.get("cancel"), "type": "button", "y": 5, "x": 10},
                ]
                title = i18n.get("add_new_group")

            final_data = self._run_form_loop(form_fields, title)

            if final_data:
                if (
                    final_data.get("name")
                    and final_data["name"] != parent_node.get("name")
                    and final_data["name"] != "Top Level"
                ):
                    existing_node, _, _ = self.host_manager.find_node_and_parent(
                        final_data["name"]
                    )
                    if existing_node:
                        self.screen.clear()
                        self.screen.addstr(
                            1, 2, i18n.get("error_name_exists", name=final_data["name"])
                        )
                        self.screen.refresh()
                        self.screen.getch()
                        return

                if node_type == "host":
                    new_node = {
                        "type": "host",
                        "name": final_data["name"],
                        "host": f"{final_data['host']}:{final_data['port']}",
                        "user": final_data["user"],
                        "password": final_data.get("password", ""),
                        "id_file": final_data.get("id_file", ""),
                        "mfa_secret": final_data.get("mfa_secret", ""),
                    }
                    if final_data.get("ssh_jump_mode") != "default":
                        new_node["ssh_jump_mode"] = final_data.get("ssh_jump_mode")
                    if final_data.get("transfer_jump_mode") != "default":
                        new_node["transfer_jump_mode"] = final_data.get(
                            "transfer_jump_mode"
                        )
                else:
                    new_node = {
                        "type": "group",
                        "name": final_data["name"],
                        "expanded": True,
                        "children": [],
                    }
                self.host_manager.add_node(new_node, parent_name)
                self.screen.clear()
                self.screen.addstr(
                    1, 2, i18n.get("success_added", name=new_node["name"])
                )
                self.screen.refresh()
                self.screen.getch()
        except Exception as e:
            self.restore_screen()
            print(f"An error occurred in add flow: {e}")
            import traceback

            traceback.print_exc()
            sys.exit(1)
        finally:
            self.mode = original_mode

    def _show_readonly_error(self):
        self.screen.clear()
        self.screen.addstr(1, 2, i18n.get("edit_ssh_config_not_supported"))
        self.screen.addstr(2, 2, i18n.get("edit_ssh_config_advice")),
        self.screen.refresh()
        self.screen.getch()

    def run_edit_flow(self):
        selected_node = self.get_current_node()
        if not selected_node or selected_node.get("source") in _AUTO_GENERATED_SOURCES:
            return

        if selected_node.get("source") in _READONLY_SOURCES:
            self._show_readonly_error()
            return

        original_name = selected_node["name"]
        node_type = selected_node["type"]

        if node_type == "host":
            current_host, current_port = self.host_manager._parse_host_port(selected_node)

            current_auth_val = "none"
            if selected_node.get("password"):
                current_auth_val = "password"
            elif selected_node.get("id_file"):
                current_auth_val = "key"

            form_fields = [
                {
                    "label": i18n.get("name"),
                    "type": "text",
                    "name": "name",
                    "y": 3,
                    "x": 2,
                    "required": True,
                    "value": selected_node.get("name", ""),
                },
                {
                    "label": i18n.get("host_domain"),
                    "type": "text",
                    "name": "host",
                    "y": 4,
                    "x": 2,
                    "required": True,
                    "value": current_host,
                },
                {
                    "label": i18n.get("port"),
                    "type": "text",
                    "name": "port",
                    "y": 5,
                    "x": 2,
                    "required": True,
                    "value": current_port,
                },
                {
                    "label": i18n.get("username"),
                    "type": "text",
                    "name": "user",
                    "y": 6,
                    "x": 2,
                    "required": True,
                    "value": selected_node.get("user", ""),
                },
                {
                    "label": i18n.get("auth_method"),
                    "type": "radio",
                    "name": "auth",
                    "options": ["password", "key", "none"],
                    "value": current_auth_val,
                    "y": 7,
                    "x": 2,
                },
                {
                    "label": i18n.get("password"),
                    "type": "password",
                    "name": "password",
                    "y": 9,
                    "x": 2,
                    "visible": (current_auth_val == "password"),
                    "required": (current_auth_val == "password"),
                    "value": selected_node.get("password", ""),
                },
                {
                    "label": i18n.get("key_path"),
                    "type": "text",
                    "name": "id_file",
                    "y": 10,
                    "x": 2,
                    "visible": (current_auth_val == "key"),
                    "required": (current_auth_val == "key"),
                    "value": selected_node.get("id_file", ""),
                },
                {
                    "label": i18n.get("mfa_secret"),
                    "type": "text",
                    "name": "mfa_secret",
                    "y": 11,
                    "x": 2,
                    "value": selected_node.get("mfa_secret", ""),
                },
                {
                    "label": i18n.get("ssh_jump_mode"),
                    "type": "radio",
                    "name": "ssh_jump_mode",
                    "options": ["default", "shell", "tunnel"],
                    "value": selected_node.get("ssh_jump_mode", "default"),
                    "y": 12,
                    "x": 2,
                },
                {
                    "label": i18n.get("transfer_jump_mode"),
                    "type": "radio",
                    "name": "transfer_jump_mode",
                    "options": ["default", "tunnel", "relay"],
                    "value": selected_node.get("transfer_jump_mode", "default"),
                    "y": 15,
                    "x": 2,
                },
                {"label": i18n.get("save"), "type": "button", "y": 19, "x": 2},
                {"label": i18n.get("cancel"), "type": "button", "y": 19, "x": 10},
            ]
            title = i18n.get("edit_host", name=original_name)
        else:  # group
            form_fields = [
                {
                    "label": i18n.get("name"),
                    "type": "text",
                    "name": "name",
                    "y": 3,
                    "x": 2,
                    "required": True,
                    "value": selected_node.get("name", ""),
                },
                {"label": i18n.get("save"), "type": "button", "y": 5, "x": 2},
                {"label": i18n.get("cancel"), "type": "button", "y": 5, "x": 10},
            ]
            title = i18n.get("edit_group", name=original_name)

        final_data = self._run_form_loop(form_fields, title)

        if final_data:
            if final_data.get("name") and final_data["name"] != original_name:
                existing_node, _, _ = self.host_manager.find_node_and_parent(
                    final_data["name"]
                )
                if existing_node:
                    self.screen.clear()
                    self.screen.addstr(
                        1, 2, i18n.get("error_name_exists", name=final_data["name"])
                    )
                    self.screen.refresh()
                    self.screen.getch()
                    return

            if node_type == "host":
                final_data["host"] = f"{final_data['host']}:{final_data['port']}"

            self.host_manager.update_node(original_name, final_data)
            self._recent_group = None
            self._recent_group_ts = 0
            self.screen.clear()
            self.screen.addstr(
                1, 2, i18n.get("success_updated", name=final_data["name"])
            )
            self.screen.refresh()
            self.screen.getch()

    def run_delete_flow(self):
        selected_node = self.get_current_node()
        if not selected_node or selected_node.get("source") in _AUTO_GENERATED_SOURCES:
            return

        if selected_node.get("source") in _READONLY_SOURCES:
            self._show_readonly_error()
            return

        title = i18n.get("confirm_deletion")

        form_fields = []
        form_fields.append(
            {
                "label": i18n.get("delete_confirm_msg", name=selected_node["name"]),
                "type": "static_text",
                "y": 3,
                "x": 2,
            }
        )

        button_y_pos = 5
        if selected_node.get("type") == "host":
            form_fields.append(
                {
                    "label": i18n.get(
                        "host_info_msg", host=selected_node.get("host", "N/A")
                    ),
                    "type": "static_text",
                    "y": 4,
                    "x": 2,
                }
            )
            button_y_pos = 6

        form_fields.append(
            {
                "label": i18n.get("yes"),
                "type": "button",
                "name": "confirm",
                "y": button_y_pos,
                "x": 5,
            }
        )
        form_fields.append(
            {"label": i18n.get("no"), "type": "button", "y": button_y_pos, "x": 15}
        )

        result = self._run_form_loop(form_fields, title)

        if result and result.get("confirm"):
            self.host_manager.delete_host(selected_node["name"])
            self.highlight_line_number = max(0, self.highlight_line_number - 1)

    def updown(self, increment):
        new_highlight_line_number = self.highlight_line_number + increment
        visible_hosts = self.get_lines_with_level()
        if visible_hosts:
            self.highlight_line_number = max(
                0, min(new_highlight_line_number, len(visible_hosts) - 1)
            )
        else:
            self.highlight_line_number = 0

    def _build_recent_group(self):
        now = time.monotonic()
        if self._recent_group is not None and now - self._recent_group_ts < 60:
            return self._recent_group

        recent_records = self.host_manager.audit.get_history(limit=10)
        if not recent_records:
            self._recent_group = None
            self._recent_group_ts = now
            return None

        children = []
        seen_keys = set()
        for record in reversed(recent_records):
            name = record.get("name", "")
            host = record.get("host", "")
            user = record.get("user", "")
            port = record.get("port")
            node_id = record.get("node_id")
            existing = self.host_manager.find_host_by_id(node_id)
            if not existing:
                existing = self.host_manager.find_host_by_alias(name)
            if existing:
                seen_key = ("current", existing.get("name", ""))
                child = existing.copy()
            else:
                current = self.host_manager.find_host_by_endpoint(host, user, port)
                if current:
                    seen_key = ("current", current.get("name", ""))
                    child = current.copy()
                else:
                    seen_key = ("history", name, host, user, port)
                    history_host = record.get("endpoint") or host
                    if port and ":" not in history_host:
                        history_host = f"{history_host}:{port}"
                    child = {
                        "type": "host",
                        "name": name,
                        "host": history_host,
                        "user": user,
                        "password": "",
                        "id_file": "",
                        "mfa_secret": "",
                        "source": "history",
                    }
            if seen_key in seen_keys:
                continue
            seen_keys.add(seen_key)
            children.append(child)

        if not children:
            self._recent_group = None
            self._recent_group_ts = now
            return None

        recent_expanded = self.host_manager.config.get("recent_expanded", False)
        self._recent_group = {
            "type": "group",
            "name": i18n.get("recent"),
            "expanded": recent_expanded,
            "children": children,
            "source": "recent_group",
        }
        self._recent_group_ts = now
        return self._recent_group

    def _get_all_nodes_with_level(self):
        lines = []
        recent_group = self._build_recent_group()
        initial_nodes = list(self.host_manager.get_hosts())
        if recent_group:
            initial_nodes.insert(0, recent_group)

        def traverse(nodes, level):
            for node in nodes:
                node["_level"] = level
                lines.append(node)
                if node.get("children") and node.get("expanded", True):
                    traverse(node.get("children", []), level + 1)

        traverse(initial_nodes, 0)
        return lines

    def get_lines_with_level(self):
        lines = self._get_all_nodes_with_level()
        if self.mode == "select_parent":
            lines.insert(
                0,
                {
                    "name": "[Top Level]",
                    "_level": 0,
                    "type": "system",
                    "expanded": True,
                },
            )

        if self.search_query:
            query = self.search_query.lower()
            return [line for line in lines if query in line.get("name", "").lower()]

        return lines

    def toggle_expansion(self):
        node = self.get_current_node()
        if node and node.get("children") is not None:
            node["expanded"] = not node.get("expanded", True)

    def handle_enter(self):
        node = self.get_current_node()
        if not node:
            return None

        if self.mode in ["select", "select_parent"]:
            return node

        if node.get("type") == "host":
            self.connect_to_node(node)
        elif node.get("type") == "group":
            if not node.get("expanded", True):
                self._set_expansion(True)
            elif not self.host_manager.contains_hosts(node):
                title = f"Group '{node.get('name')}' is empty."
                form_fields = [
                    {
                        "label": f"Add a new host to this group?",
                        "type": "static_text",
                        "y": 3,
                        "x": 2,
                    },
                    {
                        "label": i18n.get("yes"),
                        "type": "button",
                        "name": "confirm",
                        "y": 5,
                        "x": 5,
                    },
                    {"label": i18n.get("no"), "type": "button", "y": 5, "x": 15},
                ]
                result = self._run_form_loop(form_fields, title)
                if result and result.get("confirm"):
                    self.run_add_flow(preselected_parent=node)

    def get_current_node(self):
        visible_hosts = self.get_lines_with_level()
        if not visible_hosts or self.highlight_line_number >= len(visible_hosts):
            return None
        return visible_hosts[self.highlight_line_number]

    def connect_to_node(self, node):
        self.restore_screen()
        self.host_manager.execute_interactive_connection(node)
        self.exit_reason = "connected"

    def _draw_detail_pane(self, node, window):
        window.clear()
        window.border()
        height, width = window.getmaxyx()

        if not node or node.get("type") != "host":
            window.addstr(2, 2, "Select a host to see details.")
            return

        details = []
        details.append(("Name", node.get("name", "N/A")))

        host_str = node.get("host", "N/A")
        user_str = node.get("user", "N/A")
        details.append(("Target", self.host_manager._build_target_str(user_str, host_str)))

        auth_method = "None"
        if node.get("id_file"):
            auth_method = f"Key ({os.path.basename(node.get('id_file'))})"
        elif node.get("password"):
            auth_method = "Password"
        details.append(("Auth", auth_method))

        if node.get("mfa_secret"):
            details.append(("MFA/OTP", "Enabled"))

        if node.get("nest_parent"):
            details.append(("Jump Host", node["nest_parent"].get("name", "N/A")))

        y = 1
        try:
            window.addstr(y, 2, "Host Details", curses.A_BOLD | curses.A_UNDERLINE)
            y += 2

            for key, value in details:
                if y >= height - 2:
                    break
                label = f"{key}:"
                window.addstr(y, 2, label, curses.A_BOLD)
                # Word wrap for long values
                value_lines = textwrap.wrap(value, width - 4 - len(label) - 1)
                if not value_lines:
                    y += 1
                    continue

                window.addstr(y, 2 + len(label) + 1, value_lines[0])
                y += 1
                for line in value_lines[1:]:
                    if y >= height - 2:
                        break
                    window.addstr(y, 4, line)
                    y += 1
        except curses.error:
            pass  # Ignore render errors if window is too small

    def render_screen(self):
        self.screen.clear()
        screen_lines, screen_cols = self.screen.getmaxyx()

        # Footer setup
        footer_line = screen_lines - 1
        search_line = screen_lines - 2

        if self.input_mode == "search" and search_line > 0:
            search_text = f"Search: {self.search_query}"
            clear_hint = " (Ctrl+U to clear, Esc to exit)"
            if len(search_text) + len(clear_hint) < screen_cols:
                search_text += clear_hint
            self.screen.addstr(search_line, 1, search_text)
            self.screen.move(search_line, len(f"Search: {self.search_query}") + 1)
            curses.curs_set(1)
        else:
            curses.curs_set(0)

        if footer_line > 0:
            if self.input_mode == "search":
                hint_text = i18n.get("footer_search")
            elif self.mode == "select":
                hint_text = i18n.get("footer_select")
            elif self.mode == "select_parent":
                hint_text = i18n.get("footer_select_parent")
            else:
                hint_text = i18n.get("footer_main")

            self.screen.attron(curses.A_REVERSE)
            self.screen.addstr(footer_line, 0, " " * (screen_cols - 1))
            self.screen.addstr(footer_line, 1, hint_text)
            self.screen.attroff(curses.A_REVERSE)

        render_area_lines = screen_lines - (3 if self.input_mode == "search" else 2)

        lines_to_render = self.get_lines_with_level()
        if not lines_to_render:
            self.screen.addstr(
                1,
                2,
                (
                    f"No results for '{self.search_query}'"
                    if self.search_query
                    else "No hosts configured."
                ),
            )
            if not self.search_query:
                self.screen.addstr(2, 2, "Press 'a' to add a new host or 'q' to quit.")
            self.screen.refresh()
            return

        self.highlight_line_number = max(
            0, min(self.highlight_line_number, len(lines_to_render) - 1)
        )
        if self.highlight_line_number < self.top_line_number:
            self.top_line_number = self.highlight_line_number
        if self.highlight_line_number >= self.top_line_number + render_area_lines:
            self.top_line_number = self.highlight_line_number - render_area_lines + 1

        # Render the main list (full width)
        for index, node in enumerate(
            lines_to_render[
                self.top_line_number : self.top_line_number + render_area_lines
            ]
        ):
            display_name = node.get("name", "")
            prefix = "  " * node.get("_level", 0)
            if node.get("children") is not None:
                display_name += f" ({len(node.get('children', []))})"
                prefix += "-" if node.get("expanded", True) else "+"
            else:
                prefix += "o"
            prefix += " "
            if node.get("nest_parent"):
                display_name += f" -> via {node['nest_parent'].get('name')}"

            color = curses.A_NORMAL
            if self.top_line_number + index == self.highlight_line_number:
                color = curses.color_pair(self.COLOR_HIGHLIGHT)

            max_name_width = screen_cols - len(prefix) - 2
            if len(display_name) > max_name_width:
                display_name = display_name[: max_name_width - 3] + "..."

            self.screen.addstr(index + 1, 1, prefix, curses.color_pair(self.COLOR_RED))
            self.screen.addstr(index + 1, len(prefix) + 1, display_name, color)

        self.screen.refresh()

        # Render floating detail window if applicable
        MIN_COLS_FOR_PREVIEW = 80
        show_details = self.host_manager.config.get("show_detail_pane", True)
        node = self.get_current_node()
        if (
            show_details
            and screen_cols >= MIN_COLS_FOR_PREVIEW
            and node
            and node.get("type") == "host"
        ):
            win_h = screen_lines - 2
            win_w = screen_cols // 2
            win_y = 1
            win_x = screen_cols - win_w - 1
            try:
                detail_win = curses.newwin(win_h, win_w, win_y, win_x)
                self._draw_detail_pane(node, detail_win)
                detail_win.refresh()
            except curses.error:
                pass  # Fail silently if window creation fails

    def restore_screen(self):
        if hasattr(self, "screen") and self.screen:
            curses.nocbreak()
            curses.endwin()
