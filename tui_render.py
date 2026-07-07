import curses
import textwrap

from i18n import i18n
import tui_text


DEFAULT_SCREEN_SIZE = (24, 80)
DETAIL_MIN_COLS = 96
DETAIL_MIN_WIDTH = 34
DETAIL_MAX_WIDTH = 56


def window_size(window, default=DEFAULT_SCREEN_SIZE):
    try:
        return window.getmaxyx()
    except (AttributeError, curses.error):
        return default


def safe_addstr(window, y, x, text, attr=0, max_width=None):
    height, width = window_size(window)
    if y < 0 or y >= height or x < 0 or x >= width:
        return

    available = width - x - 1
    if max_width is not None:
        available = min(available, max_width)
    if available <= 0:
        return

    value = str(text)
    if tui_text.display_width(value) > available:
        value = tui_text.truncate_cells(value, max(0, available - 1))
    try:
        window.addstr(y, x, value, attr)
    except curses.error:
        pass


def draw_bar(window, y, text, attr=0):
    _, width = window_size(window)
    if width <= 1:
        return
    safe_addstr(window, y, 0, " " * (width - 1), attr)
    safe_addstr(window, y, 1, text, attr, max_width=width - 2)


def draw_shell(
    screen,
    title="",
    footer="",
    search_text="",
    frame=True,
    status_attr=0,
):
    screen.clear()
    height, width = window_size(screen)
    if frame:
        try:
            screen.border(0)
        except (AttributeError, curses.error):
            pass

    if title:
        header = f"{i18n.get('app_title')} - {title}"
        safe_addstr(screen, 0, 2, f" {header} ", curses.A_BOLD)

    footer_y = height - 1
    search_y = None
    content_bottom = footer_y
    if search_text and height > 3:
        search_y = height - 2
        content_bottom = search_y
        safe_addstr(screen, search_y, 2, search_text)

    if footer and footer_y > 0:
        draw_bar(screen, footer_y, footer, status_attr)

    return {
        "height": height,
        "width": width,
        "content_top": 1,
        "content_bottom": max(1, content_bottom),
        "footer_y": footer_y,
        "search_y": search_y,
    }


def draw_form_fields(
    window,
    visible_fields,
    active_field_index,
    screen_width,
    start_y,
    highlight_attr,
    min_input_width,
):
    for i, field in enumerate(visible_fields):
        y = field.get("_screen_y", start_y)
        x = field.get("_label_x", 3)
        input_x = field.get("_input_x", x + 2)
        input_width = field.get("_input_width", min_input_width)
        label = field.get("label", "")
        field_type = field.get("type")
        is_active = i == active_field_index
        attr = highlight_attr if is_active else curses.A_NORMAL
        right_width = max(0, screen_width - x - 2)

        if field_type == "static_text":
            for offset, line in enumerate(field.get("_wrapped_lines", [label])):
                safe_addstr(window, y + offset, x, line, max_width=right_width)
            continue

        safe_addstr(window, y, max(1, x - 2), ">" if is_active else " ", curses.A_BOLD)

        if field_type == "section":
            safe_addstr(
                window, y, x, f"-- {label} --", curses.A_BOLD, max_width=right_width
            )
        elif field_type == "toggle":
            toggle_marker = "[-]" if field.get("value") else "[+]"
            safe_addstr(
                window,
                y,
                x,
                f"{toggle_marker} {label}",
                attr | curses.A_BOLD,
                max_width=right_width,
            )
        elif field_type in ("text", "password"):
            safe_addstr(window, y, x, label, curses.A_BOLD)
            value = field.get("value") or ""
            display_value = "*" * len(value) if field_type == "password" else value
            display_value = tui_text.ellipsize(
                display_value, input_width, tail=field_type != "password"
            )
            padded_value = f" {display_value:<{input_width}} "
            safe_addstr(window, y, input_x, padded_value, attr, max_width=input_width + 2)
        elif field_type == "radio":
            safe_addstr(window, y, x, label, curses.A_BOLD)
            value = field.get("value")
            option_width = max(0, screen_width - input_x - 2)
            for j, option in enumerate(field.get("options", [])):
                option_attr = curses.A_BOLD if is_active else curses.A_NORMAL
                marker = "(x)" if value == option else "( )"
                if value == option:
                    option_attr |= attr
                option_label = f"{marker} {i18n.get(option)}"
                safe_addstr(
                    window, y + j, input_x, option_label, option_attr, max_width=option_width
                )
        elif field_type == "button":
            safe_addstr(window, y, x, f"[ {label} ]", attr)


def main_split_layout(screen_cols, node, show_detail_pane=True):
    content_width = max(1, screen_cols - 2)
    show_details = (
        show_detail_pane
        and screen_cols >= DETAIL_MIN_COLS
        and node
        and node.get("type") == "host"
    )
    if not show_details:
        return {
            "list_x": 1,
            "list_width": content_width,
            "detail_x": None,
            "detail_width": 0,
            "separator_x": None,
        }

    detail_width = min(DETAIL_MAX_WIDTH, max(DETAIL_MIN_WIDTH, screen_cols // 3))
    list_width = max(24, content_width - detail_width - 1)
    if list_width < 24:
        return {
            "list_x": 1,
            "list_width": content_width,
            "detail_x": None,
            "detail_width": 0,
            "separator_x": None,
        }

    separator_x = 1 + list_width
    return {
        "list_x": 1,
        "list_width": list_width,
        "detail_x": separator_x + 1,
        "detail_width": detail_width,
        "separator_x": separator_x,
    }


def draw_empty_list(window, split, content_top, search_query):
    x = split["list_x"] + 1
    width = max(0, split["list_width"] - 2)
    message = (
        i18n.get("no_results", query=search_query)
        if search_query
        else i18n.get("no_hosts")
    )
    safe_addstr(window, content_top, x, message, max_width=width)
    if not search_query:
        safe_addstr(window, content_top + 1, x, i18n.get("empty_hosts_hint"), max_width=width)


def draw_detail_pane(window, node, details):
    window.clear()
    height, width = window_size(window)
    try:
        window.border()
    except curses.error:
        pass

    if not node or node.get("type") != "host":
        safe_addstr(window, 2, 2, i18n.get("select_host_details"))
        return

    y = 1
    try:
        safe_addstr(
            window,
            y,
            2,
            i18n.get("host_details_title"),
            curses.A_BOLD | curses.A_UNDERLINE,
        )
        y += 2

        for key, value in details:
            if y >= height - 2:
                break
            label = f"{key}:"
            safe_addstr(window, y, 2, label, curses.A_BOLD)
            value_width = max(10, width - 4 - len(label) - 1)
            value_lines = textwrap.wrap(str(value), value_width)
            if not value_lines:
                y += 1
                continue

            safe_addstr(window, y, 2 + len(label) + 1, value_lines[0])
            y += 1
            for line in value_lines[1:]:
                if y >= height - 2:
                    break
                safe_addstr(window, y, 4, line)
                y += 1
    except curses.error:
        pass
