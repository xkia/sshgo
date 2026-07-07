#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import curses
import unicodedata


def char_width(ch):
    if unicodedata.combining(ch):
        return 0
    if unicodedata.east_asian_width(ch) in ("F", "W"):
        return 2
    return 1


def display_width(value):
    return sum(char_width(ch) for ch in str(value))


def _take_cells(value, width, tail=False):
    if width <= 0:
        return ""
    chars = reversed(str(value)) if tail else iter(str(value))
    used = 0
    output = []
    for ch in chars:
        ch_width = char_width(ch)
        if used + ch_width > width:
            break
        output.append(ch)
        used += ch_width
    if tail:
        output.reverse()
    return "".join(output)


def truncate_cells(value, width):
    value = str(value)
    if display_width(value) <= width:
        return value
    return _take_cells(value, width)


def ellipsize(value, width, tail=False):
    value = str(value)
    if width <= 0:
        return ""
    if display_width(value) <= width:
        return value
    if width <= 3:
        return _take_cells(value, width)
    if tail:
        return "..." + _take_cells(value, width - 3, tail=True)
    return _take_cells(value, width - 3) + "..."


def matches_key(key, *candidates):
    return any(key == candidate for candidate in candidates)


def insertable_text_for_key(key):
    if isinstance(key, str):
        return "".join(ch for ch in key if ch.isprintable())
    if isinstance(key, int) and 32 <= key <= 126:
        return chr(key)
    return ""


def apply_text_edit_key(value, cursor, key):
    value = str(value)
    cursor = max(0, min(int(cursor), len(value)))

    if matches_key(key, "\n", "\r", curses.KEY_ENTER, 10, 13):
        return value, cursor, "commit"
    if matches_key(key, "\x1b", 27):
        return value, cursor, "cancel"
    if matches_key(key, "\x15", 21):  # Ctrl+U
        return "", 0, None
    if matches_key(key, "\x01", 1, curses.KEY_HOME):  # Ctrl+A / Home
        return value, 0, None
    if matches_key(key, "\x05", 5, curses.KEY_END):  # Ctrl+E / End
        return value, len(value), None
    if matches_key(key, curses.KEY_LEFT):
        return value, max(0, cursor - 1), None
    if matches_key(key, curses.KEY_RIGHT):
        return value, min(len(value), cursor + 1), None
    if matches_key(key, curses.KEY_BACKSPACE, "\x7f", "\b", 127, 8):
        if cursor == 0:
            return value, cursor, None
        return value[: cursor - 1] + value[cursor:], cursor - 1, None
    if matches_key(key, curses.KEY_DC, 330):
        if cursor >= len(value):
            return value, cursor, None
        return value[:cursor] + value[cursor + 1 :], cursor, None

    insert_text = insertable_text_for_key(key)
    if insert_text:
        return (
            value[:cursor] + insert_text + value[cursor:],
            cursor + len(insert_text),
            None,
        )
    return value, cursor, None
