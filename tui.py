#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import time
import curses
import textwrap

from config_validation import DEFAULT_TUI_SCREEN_POLICY, TUI_SCREEN_POLICIES
import host_tree
from i18n import i18n
import tui_flows
import tui_forms
import tui_recent
import tui_render
import tui_text

_AUTO_GENERATED_SOURCES = tui_flows.AUTO_GENERATED_SOURCES
_READONLY_SOURCES = tui_flows.READONLY_SOURCES


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

    def _style_color(self, attr_name):
        pair_id = getattr(self, attr_name, 0)
        try:
            return curses.color_pair(pair_id) if pair_id else curses.A_NORMAL
        except curses.error:
            return curses.A_NORMAL

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
            reader = edit_win.get_wch if hasattr(edit_win, "get_wch") else edit_win.getch
            return reader()
        except (AttributeError, curses.error):
            return None

    def _edit_text_field(self, field, initial_value):
        input_width = max(
            1,
            int(field.get("_input_width", tui_forms.FORM_INPUT_MIN_WIDTH)),
        )
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
            value, cursor, action = tui_text.apply_text_edit_key(value, cursor, key)
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
            return i18n.get(
                "footer_form_radio" if field_type == "radio" else "footer_form_button"
            )

        if self.input_mode == "search":
            return i18n.get("footer_search")
        footer_key = {
            "select": "footer_select",
            "select_parent": "footer_select_parent",
        }.get(self.mode, "footer_main")
        return i18n.get(footer_key)

    def _show_message(self, title, message):
        footer = i18n.get("press_any_key")
        layout = tui_render.draw_shell(
            self.screen,
            title=title,
            footer=footer,
            status_attr=self._style_color("COLOR_STATUS"),
        )
        width = layout["width"]
        max_width = max(20, width - 6)
        lines = []
        for raw_line in str(message).splitlines() or [""]:
            wrapped = textwrap.wrap(raw_line, max_width) or [raw_line]
            lines.extend(wrapped)

        y = layout["content_top"] + 1
        for line in lines[: max(1, layout["content_bottom"] - y)]:
            tui_render.safe_addstr(self.screen, y, 3, line, max_width=width - 6)
            y += 1
        self.screen.refresh()
        self.screen.getch()

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

                if c in (27, ord("q")):
                    if self.input_mode == "search":
                        self.input_mode = "navigate"
                        self.search_query = ""
                        if c == 27:
                            self.highlight_line_number = 0
                    elif self.mode in ["select", "select_parent"]:
                        return None
                    elif c == ord("q"):
                        break
                    continue

                if c in (curses.KEY_UP, ord("k")):
                    self.updown(-1)
                elif c in (curses.KEY_DOWN, ord("j")):
                    self.updown(1)
                elif c in (curses.KEY_ENTER, 10, 13):
                    result = self.handle_enter()
                    if self.exit_reason == "connected":
                        return
                    if self.mode in ["select", "select_parent"]:
                        return result

                elif self.input_mode == "navigate":
                    if c in (ord("l"), curses.KEY_RIGHT):
                        self._set_expansion(True)
                    elif c in (ord("h"), curses.KEY_LEFT):
                        self._set_expansion(False)
                    elif c == ord("f"):
                        self.input_mode = "search"
                    elif c == ord("a"):
                        tui_flows.run_add_flow(self)
                    elif c == ord("e"):
                        tui_flows.run_edit_flow(self)
                    elif c == ord("d"):
                        tui_flows.run_delete_flow(self)

                elif self.input_mode == "search":
                    if c in (curses.KEY_BACKSPACE, 127):
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
        layout = tui_render.draw_shell(
            self.screen,
            title=title,
            footer=self._footer_for_state(active_field),
            status_attr=self._style_color("COLOR_STATUS"),
        )
        screen_height = layout["height"]
        screen_width = layout["width"]
        start_y = layout["content_top"] + 1
        form_layout = tui_forms.layout_form_fields(
            visible_fields,
            screen_width,
            start_y,
        )

        required_height = start_y + form_layout["required_height"] + 2
        required_width = (
            form_layout["input_x"]
            + max(tui_forms.FORM_INPUT_MIN_WIDTH, form_layout["input_width"])
            + 4
        )
        if screen_height < required_height or screen_width < required_width:
            message = i18n.get(
                "terminal_too_small",
                width=required_width,
                height=required_height,
            )
            tui_render.safe_addstr(
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
            tui_render.safe_addstr(
                self.screen,
                layout["content_bottom"] - 1,
                3,
                error_message,
                self._style_color("COLOR_WARNING"),
                max_width=max(0, screen_width - 6),
            )

        tui_render.draw_form_fields(
            self.screen,
            visible_fields,
            active_field_index,
            screen_width,
            start_y,
            self._style_color("COLOR_HIGHLIGHT"),
            tui_forms.FORM_INPUT_MIN_WIDTH,
        )

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
        form_data = tui_forms.form_data_from_fields(fields)
        error_message = ""

        while True:
            # Dynamically adjust field visibility based on other field values
            tui_forms.apply_dynamic_visibility(fields, form_data)

            visible_fields = tui_forms.visible_form_fields(fields)
            tui_forms.sync_field_values(visible_fields, form_data)

            if not visible_fields:
                return None

            interactive_fields = tui_forms.interactive_form_fields(visible_fields)
            if not interactive_fields:
                self._draw_form(visible_fields, -1, title, error_message)
                c = self.screen.getch()
                if c in (27, ord("q")):
                    return None
                continue

            if active_field_index >= len(interactive_fields):
                active_field_index = len(interactive_fields) - 1
            if pending_focus_name:
                focus_index = tui_forms.interactive_index_by_name(
                    interactive_fields,
                    pending_focus_name,
                )
                if focus_index is not None:
                    active_field_index = focus_index
                    pending_focus_name = None

            full_index = visible_fields.index(interactive_fields[active_field_index])

            form_drawn = self._draw_form(visible_fields, full_index, title, error_message)
            c = self.screen.getch()
            if not form_drawn:
                if c in (27, ord("q")):
                    return None
                continue
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
                    tui_forms.advance_radio_value(form_data, active_field)

                elif field_type == "toggle":
                    tui_forms.toggle_field_value(form_data, active_field)

                elif field_type == "button":
                    button_label = active_field.get("label")
                    if button_label in [i18n.get("cancel"), i18n.get("no")]:
                        return None
                    if button_label in [i18n.get("yes"), i18n.get("delete")]:
                        form_data["confirm"] = True
                        return form_data
                    if button_label in [i18n.get("save"), i18n.get("continue")]:
                        if button_label == i18n.get("save"):
                            error_message, pending_focus_name = (
                                tui_forms.first_required_error(
                                    visible_fields,
                                    form_data,
                                )
                            )
                            if error_message:
                                continue
                            if validator:
                                errors, focus_name = tui_forms.normalize_validation_result(
                                    validator(form_data)
                                )
                                if errors:
                                    error_message = errors[0]
                                    pending_focus_name = tui_forms.set_pending_focus(
                                        fields,
                                        form_data,
                                        focus_name,
                                    )
                                    continue
                        return form_data
            elif c == ord(" "):
                if active_field.get("type") == "radio":
                    tui_forms.advance_radio_value(form_data, active_field)
                elif active_field.get("type") == "toggle":
                    tui_forms.toggle_field_value(form_data, active_field)
            elif c in [ord("q"), 27]:
                return None

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

    def _append_expanded_nodes(self, lines, nodes, level=0, editable_only=False):
        for node in nodes:
            if editable_only and not self._is_editable_parent(node):
                continue
            node["_level"] = level
            lines.append(node)
            if node.get("children") and node.get("expanded", True):
                self._append_expanded_nodes(
                    lines, node.get("children", []), level + 1, editable_only
                )

    def _get_all_nodes_with_level(self):
        lines = []
        recent_group = self._build_recent_group()
        initial_nodes = list(self.host_manager.get_hosts())
        if recent_group:
            initial_nodes.insert(0, recent_group)
        self._append_expanded_nodes(lines, initial_nodes)
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

        self._append_expanded_nodes(
            lines, self.host_manager.get_hosts(), editable_only=True
        )
        return lines

    def get_lines_with_level(self):
        lines = (
            self._get_parent_select_lines()
            if self.mode == "select_parent"
            else self._get_all_nodes_with_level()
        )
        if self.search_query:
            query = self.search_query.lower()
            return [line for line in lines if query in line.get("name", "").lower()]
        return lines

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
            elif not host_tree.contains_hosts(node):
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
                    tui_flows.run_add_flow(self, preselected_parent=node)

    def get_current_node(self):
        visible_hosts = self.get_lines_with_level()
        if not visible_hosts or self.highlight_line_number >= len(visible_hosts):
            return None
        return visible_hosts[self.highlight_line_number]

    def connect_to_node(self, node):
        self.restore_screen()
        self.host_manager.execute_interactive_connection(node)
        self.exit_reason = "connected"

    def render_screen(self):
        node = self.get_current_node()
        _, screen_cols = tui_render.window_size(self.screen)
        search_text = ""
        if self.input_mode == "search":
            search_text = f"{i18n.get('search_label')}: {self.search_query}"
            hint = i18n.get("search_clear_hint")
            if len(search_text) + len(hint) + 3 < screen_cols:
                search_text = f"{search_text}  {hint}"

        layout = tui_render.draw_shell(
            self.screen,
            title="",
            footer=self._footer_for_state(),
            search_text=search_text,
            frame=False,
            status_attr=self._style_color("COLOR_STATUS"),
        )
        screen_cols = layout["width"]
        content_top = layout["content_top"]
        content_bottom = layout["content_bottom"]
        render_area_lines = max(1, content_bottom - content_top)

        try:
            curses.curs_set(1 if self.input_mode == "search" else 0)
            if self.input_mode == "search":
                prompt = f"{i18n.get('search_label')}: {self.search_query}"
                if layout["search_y"] is not None:
                    self.screen.move(
                        layout["search_y"],
                        min(len(prompt) + 2, screen_cols - 2),
                    )
        except curses.error:
            pass

        split = tui_render.main_split_layout(
            screen_cols,
            node,
            show_detail_pane=self.host_manager.config.get("show_detail_pane", True),
        )
        lines_to_render = self.get_lines_with_level()
        if not lines_to_render:
            tui_render.draw_empty_list(
                self.screen,
                split,
                content_top,
                self.search_query,
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
                tui_render.safe_addstr(self.screen, y, split["separator_x"], "|")

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

            max_name_width = max(1, split["list_width"] - len(prefix) - 2)
            display_name = tui_text.ellipsize(display_name, max_name_width)
            color = (
                self._style_color("COLOR_HIGHLIGHT")
                if self.top_line_number + index == self.highlight_line_number
                else curses.A_NORMAL
            )
            y = content_top + index
            x = split["list_x"]
            tui_render.safe_addstr(
                self.screen, y, x, prefix, self._style_color("COLOR_RED")
            )
            tui_render.safe_addstr(
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
                detail_node = self.get_current_node()
                details = []
                if detail_node and detail_node.get("type") == "host":
                    details = self.host_manager.describe_host(detail_node)
                tui_render.draw_detail_pane(detail_win, detail_node, details)
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
