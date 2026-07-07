#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import time
import curses
import textwrap
import curses.textpad as textpad

from config_validation import DEFAULT_TUI_SCREEN_POLICY, TUI_SCREEN_POLICIES
from host_manager import HostManager
from i18n import i18n
import tui_flows
import tui_forms
import tui_recent
import tui_render
import tui_text

_AUTO_GENERATED_SOURCES = tui_flows.AUTO_GENERATED_SOURCES
_READONLY_SOURCES = tui_flows.READONLY_SOURCES

FORM_INPUT_MIN_WIDTH = 18
FORM_INPUT_MAX_WIDTH = 52


class Tui:
    def __init__(self, host_manager, mode="connect"):
        self.host_manager = host_manager
        self.mode = mode
        self.exit_reason = None
        self._screen_restored = False
        self.screen = None
        self.screen_policy = self._effective_screen_policy()
        self._alternate_screen_supported = self.terminal_supports_alternate_screen()
        try:
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

            self._init_theme()

            self.search_query = ""
            self.input_mode = "navigate"  # Modes: navigate, search
        except BaseException:
            self.restore_screen()
            raise

    def _init_theme(self):
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
        if isinstance(user_theme, dict):
            theme.update(user_theme)

        curses.start_color()
        curses.use_default_colors()

        hl_fg = self.COLOR_MAP.get(theme["highlight_fg"], -1)
        hl_bg = self.COLOR_MAP.get(theme["highlight_bg"], -1)
        curses.init_pair(2, hl_fg, hl_bg)
        self.COLOR_HIGHLIGHT = 2

        prefix_fg = self.COLOR_MAP.get(theme["prefix_color"], -1)
        curses.init_pair(3, prefix_fg, -1)
        self.COLOR_RED = 3
        self.COLOR_ACCENT = 3
        self.COLOR_STATUS = 0

        curses.init_pair(5, curses.COLOR_YELLOW, -1)
        self.COLOR_WARNING = 5

    def __del__(self):
        self.restore_screen()

    def _effective_screen_policy(self):
        config = getattr(self.host_manager, "config", {}) or {}
        if not isinstance(config, dict):
            return DEFAULT_TUI_SCREEN_POLICY
        policy = config.get("tui_screen_policy", DEFAULT_TUI_SCREEN_POLICY)
        if not isinstance(policy, str) or policy not in TUI_SCREEN_POLICIES:
            return DEFAULT_TUI_SCREEN_POLICY
        return policy

    @staticmethod
    def terminal_supports_alternate_screen():
        try:
            curses.setupterm()
            return bool(curses.tigetstr("smcup") and curses.tigetstr("rmcup"))
        except (curses.error, OSError, TypeError):
            return False

    def _clear_terminal_scrollback(self):
        try:
            sys.stdout.write("\033[H\033[2J\033[3J")
            sys.stdout.flush()
        except OSError:
            pass

    def _window_size(self, window=None):
        return tui_render.window_size(window or self.screen)

    def _color(self, pair_id):
        try:
            return curses.color_pair(pair_id)
        except curses.error:
            return curses.A_NORMAL

    def _style_color(self, attr_name):
        pair_id = getattr(self, attr_name, 0)
        if not pair_id:
            return curses.A_NORMAL
        return self._color(pair_id)

    def _safe_addstr(self, window, y, x, text, attr=0, max_width=None):
        tui_render.safe_addstr(window, y, x, text, attr, max_width=max_width)

    def _ellipsize(self, value, width, tail=False):
        return tui_text.ellipsize(value, width, tail=tail)

    def _matches_key(self, key, *candidates):
        return tui_text.matches_key(key, *candidates)

    def _insertable_text_for_key(self, key):
        return tui_text.insertable_text_for_key(key)

    def _apply_text_edit_key(self, value, cursor, key):
        return tui_text.apply_text_edit_key(value, cursor, key)

    def _draw_edit_window(self, edit_win, value, cursor, input_width, password=False):
        input_width = max(1, int(input_width))
        display_value = "*" * len(value) if password else value
        start = max(0, cursor - input_width)
        visible_value = display_value[start : start + input_width]
        try:
            edit_win.clear()
            edit_win.addstr(0, 0, f"{visible_value:<{input_width}}")
            edit_win.move(0, min(max(0, cursor - start), input_width))
            edit_win.refresh()
        except (AttributeError, curses.error):
            pass

    def _read_edit_key(self, edit_win):
        try:
            return edit_win.get_wch()
        except AttributeError:
            try:
                return edit_win.getch()
            except curses.error:
                return None
        except curses.error:
            return None

    def _edit_text_field(self, field, initial_value):
        input_width = max(1, int(field.get("_input_width", FORM_INPUT_MIN_WIDTH)))
        try:
            edit_win = curses.newwin(
                1,
                input_width + 2,
                field.get("_screen_y", 1),
                field.get("_input_x", 1),
            )
        except curses.error:
            return str(initial_value or ""), True

        try:
            curses.curs_set(1)
        except curses.error:
            pass
        try:
            edit_win.bkgd(" ", self._style_color("COLOR_HIGHLIGHT"))
        except (AttributeError, curses.error):
            pass
        try:
            edit_win.keypad(True)
        except (AttributeError, curses.error):
            pass

        value = str(initial_value or "")
        cursor = len(value)
        cancelled = False
        while True:
            self._draw_edit_window(
                edit_win,
                value,
                cursor,
                input_width,
                password=field.get("type") == "password",
            )
            key = self._read_edit_key(edit_win)
            if key is None:
                continue
            value, cursor, action = self._apply_text_edit_key(value, cursor, key)
            if action == "commit":
                break
            if action == "cancel":
                cancelled = True
                break

        try:
            curses.curs_set(0)
        except curses.error:
            pass
        try:
            self.screen.touchwin()
        except (AttributeError, curses.error):
            pass
        try:
            self.screen.refresh()
        except (AttributeError, curses.error):
            pass
        return value, cancelled

    def _footer_for_state(self, active_field=None):
        if active_field is not None:
            field_type = active_field.get("type")
            if field_type in ("text", "password"):
                return i18n.get("footer_form_text")
            if field_type == "radio":
                return i18n.get("footer_form_radio")
            return i18n.get("footer_form_button")

        if self.input_mode == "search":
            return i18n.get("footer_search")
        if self.mode == "select":
            return i18n.get("footer_select")
        if self.mode == "select_parent":
            return i18n.get("footer_select_parent")
        return i18n.get("footer_main")

    def _draw_bar(self, window, y, text, attr=0):
        tui_render.draw_bar(window, y, text, attr)

    def _draw_shell(self, title="", footer="", search_text="", frame=True):
        return tui_render.draw_shell(
            self.screen,
            title=title,
            footer=footer,
            search_text=search_text,
            frame=frame,
            status_attr=self._style_color("COLOR_STATUS"),
        )

    def _show_message(self, title, message):
        footer = i18n.get("press_any_key")
        layout = self._draw_shell(title=title, footer=footer)
        width = layout["width"]
        max_width = max(20, width - 6)
        lines = []
        for raw_line in str(message).splitlines() or [""]:
            wrapped = textwrap.wrap(raw_line, max_width) or [raw_line]
            lines.extend(wrapped)

        y = layout["content_top"] + 1
        for line in lines[: max(1, layout["content_bottom"] - y)]:
            self._safe_addstr(self.screen, y, 3, line, max_width=width - 6)
            y += 1
        self.screen.refresh()
        self.screen.getch()

    def _main_split_layout(self, screen_cols, node):
        return tui_render.main_split_layout(
            screen_cols,
            node,
            show_detail_pane=self.host_manager.config.get("show_detail_pane", True),
        )

    def _layout_form_fields(self, visible_fields, width, start_y=2):
        label_width = 0
        labels = [
            len(field.get("label", ""))
            for field in visible_fields
            if field.get("type") not in ("static_text", "section", "button", "toggle")
        ]
        if labels:
            label_width = min(max(labels), max(10, width // 3))

        left_x = 3
        input_x = min(left_x + label_width + 2, max(left_x + 1, width - 8))
        input_width = min(
            FORM_INPUT_MAX_WIDTH,
            max(FORM_INPUT_MIN_WIDTH, width - input_x - 4),
        )

        y = start_y
        i = 0
        while i < len(visible_fields):
            field = visible_fields[i]
            field_type = field.get("type")

            if field_type == "button":
                if y > start_y:
                    y += 1
                x = left_x
                while (
                    i < len(visible_fields)
                    and visible_fields[i].get("type") == "button"
                ):
                    button = visible_fields[i]
                    button["_screen_y"] = y
                    button["_label_x"] = x
                    button["_input_x"] = x
                    button["_input_width"] = len(button.get("label", "")) + 4
                    x += button["_input_width"] + 2
                    i += 1
                y += 1
                continue

            if field_type == "section":
                if y > start_y:
                    y += 1
                field["_screen_y"] = y
                field["_label_x"] = left_x
                field["_input_x"] = left_x
                field["_input_width"] = max(20, width - left_x - 4)
                y += 1
                i += 1
                continue

            field["_screen_y"] = y
            field["_label_x"] = left_x
            field["_input_x"] = input_x
            field["_input_width"] = input_width

            if field_type == "static_text":
                text_width = max(20, width - left_x - 4)
                field["_wrapped_lines"] = textwrap.wrap(
                    field.get("label", ""),
                    text_width,
                ) or [field.get("label", "")]
                y += len(field["_wrapped_lines"])
            elif field_type == "toggle":
                y += 1
            elif field_type == "radio":
                field["_radio_height"] = max(1, len(field.get("options", [])))
                y += field["_radio_height"]
            else:
                y += 1
            i += 1

        return {
            "label_width": label_width,
            "input_x": input_x,
            "input_width": input_width,
            "required_height": max(1, y - start_y),
        }

    def _clean_form_data(self, form_data):
        return tui_forms.clean_form_data(form_data)

    def _host_form_fields(
        self,
        values=None,
        include_proxy=True,
        advanced_open=False,
        include_context=False,
    ):
        return tui_forms.host_form_fields(
            values=values,
            include_proxy=include_proxy,
            advanced_open=advanced_open,
            include_context=include_context,
        )

    def _group_form_fields(self, name=""):
        return tui_forms.group_form_fields(name)

    def _host_node_from_form(self, final_data):
        return tui_forms.host_node_from_form(final_data)

    def _group_node_from_form(self, final_data):
        return tui_forms.group_node_from_form(final_data)

    def _update_data_from_form(self, final_data):
        return tui_forms.update_data_from_form(final_data)

    def _infer_validation_focus(self, errors):
        joined = "\n".join(errors).lower()
        if "duplicate node name" in joined or "name" in joined:
            return "name"
        if "port" in joined:
            return "port"
        if "proxy" in joined:
            return "proxy_command"
        if "ssh_jump" in joined:
            return "ssh_jump_mode"
        if "transfer" in joined or "relay" in joined:
            return "transfer_jump_mode"
        if "auth" in joined or "credential" in joined:
            return "auth"
        if "host" in joined or "placeholder" in joined:
            return "host"
        return None

    def _normalize_validation_result(self, result):
        if not result:
            return [], None
        if isinstance(result, tuple):
            errors, focus_name = result
        else:
            errors, focus_name = result, None
        if isinstance(errors, str):
            errors = [errors]
        return list(errors), focus_name or self._infer_validation_focus(errors)

    def _set_pending_focus(self, fields, form_data, focus_name):
        if not focus_name:
            return None
        for field in fields:
            if field.get("name") == focus_name and field.get("advanced"):
                form_data["_advanced_open"] = True
                break
        return focus_name

    def _interactive_index_by_name(self, interactive_fields, name):
        if not name:
            return None
        for index, field in enumerate(interactive_fields):
            if field.get("name") == name:
                return index
        return None

    def _count_descendants(self, node):
        return tui_flows.count_descendants(node)

    def _delete_impact_text(self, node):
        return tui_flows.delete_impact_text(self, node)

    def _set_expansion(self, expand: bool):
        visible_nodes = self.get_lines_with_level()
        if not visible_nodes:
            return

        self.highlight_line_number = max(
            0,
            min(self.highlight_line_number, len(visible_nodes) - 1),
        )
        node = visible_nodes[self.highlight_line_number]
        target = node
        target_index = self.highlight_line_number

        if not expand and target.get("children") is None:
            current_level = target.get("_level", 0)
            for index in range(self.highlight_line_number - 1, -1, -1):
                candidate = visible_nodes[index]
                if (
                    candidate.get("children") is not None
                    and candidate.get("_level", 0) < current_level
                ):
                    target = candidate
                    target_index = index
                    break

        if not target or target.get("children") is None:
            return

        target["expanded"] = expand
        if target.get("source") == "recent_group":
            self.host_manager.config["recent_expanded"] = expand
            self.host_manager._save_hosts()
            self._recent_group = None

        if not expand:
            self.highlight_line_number = target_index

        updated_nodes = self.get_lines_with_level()
        if updated_nodes:
            self.highlight_line_number = max(
                0,
                min(self.highlight_line_number, len(updated_nodes) - 1),
            )

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
                    if c in (ord("l"), curses.KEY_RIGHT):
                        self._set_expansion(True)
                    elif c in (ord("h"), curses.KEY_LEFT):
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
        active_field = (
            visible_fields[active_field_index]
            if 0 <= active_field_index < len(visible_fields)
            else None
        )
        layout = self._draw_shell(
            title=title,
            footer=self._footer_for_state(active_field),
        )
        screen_height = layout["height"]
        screen_width = layout["width"]
        start_y = layout["content_top"] + 1
        form_layout = self._layout_form_fields(visible_fields, screen_width, start_y)

        required_height = start_y + form_layout["required_height"] + 2
        required_width = (
            form_layout["input_x"]
            + max(FORM_INPUT_MIN_WIDTH, form_layout["input_width"])
            + 4
        )
        if screen_height < required_height or screen_width < required_width:
            message = i18n.get(
                "terminal_too_small",
                width=required_width,
                height=required_height,
            )
            self._safe_addstr(
                self.screen,
                layout["content_top"] + 1,
                2,
                message,
                self._style_color("COLOR_WARNING"),
                max_width=max(0, screen_width - 4),
            )
            self.screen.refresh()
            return False

        if error_message:
            self._safe_addstr(
                self.screen,
                layout["content_bottom"] - 1,
                3,
                error_message,
                self._style_color("COLOR_WARNING"),
                max_width=max(0, screen_width - 6),
            )

        for i, field in enumerate(visible_fields):
            y = field.get("_screen_y", start_y)
            x = field.get("_label_x", 3)
            input_x = field.get("_input_x", x + 2)
            input_width = field.get("_input_width", FORM_INPUT_MIN_WIDTH)
            label = field.get("label", "")

            is_active = i == active_field_index
            attr = (
                self._style_color("COLOR_HIGHLIGHT")
                if is_active
                else curses.A_NORMAL
            )

            if field["type"] == "static_text":
                for offset, line in enumerate(field.get("_wrapped_lines", [label])):
                    self._safe_addstr(
                        self.screen,
                        y + offset,
                        x,
                        line,
                        max_width=max(0, screen_width - x - 2),
                    )
                continue

            marker = ">" if is_active else " "
            self._safe_addstr(self.screen, y, max(1, x - 2), marker, curses.A_BOLD)

            if field["type"] == "section":
                self._safe_addstr(
                    self.screen,
                    y,
                    x,
                    f"-- {label} --",
                    curses.A_BOLD,
                    max_width=max(0, screen_width - x - 2),
                )

            elif field["type"] == "toggle":
                value = bool(field.get("value"))
                toggle_marker = "[-]" if value else "[+]"
                self._safe_addstr(
                    self.screen,
                    y,
                    x,
                    f"{toggle_marker} {label}",
                    attr | curses.A_BOLD,
                    max_width=max(0, screen_width - x - 2),
                )

            elif field["type"] in ["text", "password"]:
                self._safe_addstr(self.screen, y, x, label, curses.A_BOLD)
                value = field.get("value") or ""
                display_value = (
                    "*" * len(value) if field["type"] == "password" else value
                )
                display_value = self._ellipsize(
                    display_value,
                    input_width,
                    tail=field["type"] != "password",
                )
                self._safe_addstr(
                    self.screen,
                    y,
                    input_x,
                    f" {display_value:<{input_width}} ",
                    attr,
                    max_width=input_width + 2,
                )

            elif field["type"] == "radio":
                self._safe_addstr(self.screen, y, x, label, curses.A_BOLD)
                value = field.get("value")
                for j, option in enumerate(field["options"]):
                    display_option = i18n.get(option)
                    option_attr = (
                        curses.A_BOLD if is_active else curses.A_NORMAL
                    )
                    marker = "(x)" if value == option else "( )"
                    if value == option:
                        option_attr |= attr
                    self._safe_addstr(
                        self.screen,
                        y + j,
                        input_x,
                        f"{marker} {display_option}",
                        option_attr,
                        max_width=max(0, screen_width - input_x - 2),
                    )

            elif field["type"] == "button":
                self._safe_addstr(self.screen, y, x, f"[ {label} ]", attr)

        self.screen.refresh()
        return True

    def _run_form_loop(
        self,
        fields,
        title="",
        validator=None,
        initial_focus_name=None,
    ):
        active_field_index = 0
        pending_focus_name = initial_focus_name
        form_data = {}
        for field in fields:
            if field.get("name"):
                form_data[field["name"]] = field.get("value")

        error_message = ""

        while True:
            # Dynamically adjust field visibility based on other field values
            tui_forms.apply_dynamic_visibility(fields, form_data)

            visible_fields = [f for f in fields if f.get("visible", True)]

            for field in visible_fields:
                if field.get("name") in form_data:
                    field["value"] = form_data.get(field["name"])

            if not visible_fields:
                return None

            # Filter out non-interactive fields for indexing
            interactive_fields = [
                f
                for f in visible_fields
                if f.get("type") not in ("static_text", "section")
            ]
            if not interactive_fields:
                # If no interactive fields, wait for Esc or q to exit
                if not self._draw_form(visible_fields, -1, title, error_message):
                    c = self.screen.getch()
                    if c in [27, ord("q")]:
                        return None
                    continue
                c = self.screen.getch()
                if c in [27, ord("q")]:
                    return None
                continue

            if active_field_index >= len(interactive_fields):
                active_field_index = len(interactive_fields) - 1
            if pending_focus_name:
                focus_index = self._interactive_index_by_name(
                    interactive_fields,
                    pending_focus_name,
                )
                if focus_index is not None:
                    active_field_index = focus_index
                    pending_focus_name = None

            # Find the index of the active field in the full visible_fields list
            full_index = visible_fields.index(interactive_fields[active_field_index])

            if not self._draw_form(visible_fields, full_index, title, error_message):
                c = self.screen.getch()
                if c in [27, ord("q")]:
                    return None
                continue
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
                    value, cancelled = self._edit_text_field(
                        active_field,
                        form_data.get(active_field["name"], ""),
                    )
                    if cancelled:
                        continue
                    form_data[active_field["name"]] = value.strip()
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

                elif field_type == "toggle":
                    name = active_field.get("name")
                    form_data[name] = not bool(form_data.get(name))

                elif field_type == "button":
                    button_label = active_field.get("label")
                    if button_label in [i18n.get("cancel"), i18n.get("no")]:
                        return None
                    if button_label in [i18n.get("yes"), i18n.get("delete")]:
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
                                    pending_focus_name = field.get("name")
                                    is_valid = False
                                    break
                            if not is_valid:
                                continue
                            if validator:
                                errors, focus_name = self._normalize_validation_result(
                                    validator(form_data)
                                )
                                if errors:
                                    error_message = errors[0]
                                    pending_focus_name = self._set_pending_focus(
                                        fields,
                                        form_data,
                                        focus_name,
                                    )
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
                elif active_field.get("type") == "toggle":
                    name = active_field.get("name")
                    form_data[name] = not bool(form_data.get(name))
            elif c in [ord("q"), 27]:
                return None

    def run_add_flow(self, preselected_parent=None):
        return tui_flows.run_add_flow(self, preselected_parent=preselected_parent)

    def _show_readonly_error(self):
        return tui_flows.show_readonly_error(self)

    def _show_save_error(self):
        return tui_flows.show_save_error(self)

    def _show_error(self, message):
        return tui_flows.show_error(self, message)

    def _show_success(self, message):
        return tui_flows.show_success(self, message)

    def run_edit_flow(self):
        return tui_flows.run_edit_flow(self)

    def run_delete_flow(self):
        return tui_flows.run_delete_flow(self)

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
        if not self.host_manager.config.get("show_recent", True):
            self._recent_group = None
            self._recent_group_ts = now
            return None

        if self._recent_group is not None and now - self._recent_group_ts < 60:
            return self._recent_group

        self._recent_group = tui_recent.build_recent_group(self.host_manager)
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

    def _is_editable_parent(self, node):
        if not node:
            return False
        if node.get("type") == "system":
            return True
        if node.get("type") not in ("host", "group"):
            return False
        source = node.get("source")
        return source not in _AUTO_GENERATED_SOURCES and source not in _READONLY_SOURCES

    def _get_parent_select_lines(self):
        lines = [
            {
                "name": "[Top Level]",
                "_level": 0,
                "type": "system",
                "expanded": True,
            }
        ]

        def traverse(nodes, level):
            for node in nodes:
                if not self._is_editable_parent(node):
                    continue
                node["_level"] = level
                lines.append(node)
                if node.get("children") and node.get("expanded", True):
                    traverse(node.get("children", []), level + 1)

        traverse(self.host_manager.get_hosts(), 0)
        return lines

    def get_lines_with_level(self):
        if self.mode == "select_parent":
            lines = self._get_parent_select_lines()
            if self.search_query:
                query = self.search_query.lower()
                return [
                    line for line in lines if query in line.get("name", "").lower()
                ]
            return lines

        lines = self._get_all_nodes_with_level()

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
            if node.get("children"):
                self._set_expansion(not node.get("expanded", True))
            elif not node.get("expanded", True):
                self._set_expansion(True)
            elif not self.host_manager.contains_hosts(node):
                title = i18n.get("empty_group_title", name=node.get("name"))
                form_fields = [
                    {
                        "label": i18n.get("empty_group_add_prompt"),
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
        details = []
        if node and node.get("type") == "host":
            details = self.host_manager.describe_host(node)
        tui_render.draw_detail_pane(window, node, details)

    def render_screen(self):
        node = self.get_current_node()
        search_text = ""
        if self.input_mode == "search":
            search_text = f"{i18n.get('search_label')}: {self.search_query}"
            hint = i18n.get("search_clear_hint")
            _, screen_cols = self._window_size()
            if len(search_text) + len(hint) + 3 < screen_cols:
                search_text = f"{search_text}  {hint}"

        layout = self._draw_shell(
            title="",
            footer=self._footer_for_state(),
            search_text=search_text,
            frame=False,
        )
        screen_cols = layout["width"]
        content_top = layout["content_top"]
        content_bottom = layout["content_bottom"]
        render_area_lines = max(1, content_bottom - content_top)

        if self.input_mode == "search":
            try:
                curses.curs_set(1)
                prompt = f"{i18n.get('search_label')}: {self.search_query}"
                if layout["search_y"] is not None:
                    self.screen.move(
                        layout["search_y"],
                        min(len(prompt) + 2, screen_cols - 2),
                    )
            except curses.error:
                pass
        else:
            try:
                curses.curs_set(0)
            except curses.error:
                pass

        split = self._main_split_layout(screen_cols, node)
        lines_to_render = self.get_lines_with_level()
        if not lines_to_render:
            message = (
                i18n.get("no_results", query=self.search_query)
                if self.search_query
                else i18n.get("no_hosts")
            )
            self._safe_addstr(
                self.screen,
                content_top,
                split["list_x"] + 1,
                message,
                max_width=max(0, split["list_width"] - 2),
            )
            if not self.search_query:
                self._safe_addstr(
                    self.screen,
                    content_top + 1,
                    split["list_x"] + 1,
                    i18n.get("empty_hosts_hint"),
                    max_width=max(0, split["list_width"] - 2),
                )
            self.screen.refresh()
            return

        self.highlight_line_number = max(
            0, min(self.highlight_line_number, len(lines_to_render) - 1)
        )
        if self.highlight_line_number < self.top_line_number:
            self.top_line_number = self.highlight_line_number
        if self.highlight_line_number >= self.top_line_number + render_area_lines:
            self.top_line_number = self.highlight_line_number - render_area_lines + 1

        if split["separator_x"] is not None:
            for y in range(content_top, content_bottom):
                self._safe_addstr(self.screen, y, split["separator_x"], "|")

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
                color = self._style_color("COLOR_HIGHLIGHT")

            max_name_width = max(1, split["list_width"] - len(prefix) - 2)
            display_name = self._ellipsize(display_name, max_name_width)

            y = content_top + index
            x = split["list_x"]
            self._safe_addstr(self.screen, y, x, prefix, self._style_color("COLOR_RED"))
            self._safe_addstr(
                self.screen,
                y,
                x + len(prefix),
                display_name,
                color,
                max_width=max_name_width,
            )

        self.screen.refresh()

        if split["detail_x"] is not None:
            win_h = max(1, content_bottom - content_top)
            win_w = split["detail_width"]
            win_y = content_top
            win_x = split["detail_x"]
            try:
                detail_win = curses.newwin(win_h, win_w, win_y, win_x)
                self._draw_detail_pane(self.get_current_node(), detail_win)
                detail_win.refresh()
            except curses.error:
                pass

    def restore_screen(self):
        if getattr(self, "_screen_restored", False):
            return
        self._screen_restored = True

        screen = getattr(self, "screen", None)
        if screen:
            actions = [lambda: screen.keypad(0)]
            if not getattr(self, "_alternate_screen_supported", False):
                actions.extend((lambda: screen.clear(), lambda: screen.refresh()))

            for action in actions:
                try:
                    action()
                except (curses.error, AttributeError):
                    pass

        for action in (
            lambda: curses.curs_set(1),
            curses.nocbreak,
            curses.echo,
            curses.endwin,
        ):
            try:
                action()
            except (curses.error, AttributeError):
                pass

        if getattr(self, "screen_policy", DEFAULT_TUI_SCREEN_POLICY) == "private":
            self._clear_terminal_scrollback()
