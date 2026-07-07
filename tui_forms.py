#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import getpass
import textwrap

from endpoint import DEFAULT_PORT, normalize_port
from i18n import i18n


FORM_INPUT_MIN_WIDTH = 18
FORM_INPUT_MAX_WIDTH = 52


def layout_form_fields(visible_fields, width, start_y=2):
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
            while i < len(visible_fields) and visible_fields[i].get("type") == "button":
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


def infer_validation_focus(errors):
    joined = "\n".join(errors).lower()
    focus_rules = (
        (("duplicate node name", "name"), "name"),
        (("port",), "port"),
        (("proxy",), "proxy_command"),
        (("ssh_jump",), "ssh_jump_mode"),
        (("transfer", "relay"), "transfer_jump_mode"),
        (("auth", "credential"), "auth"),
        (("host", "placeholder"), "host"),
    )
    for keywords, focus_name in focus_rules:
        if any(keyword in joined for keyword in keywords):
            return focus_name
    return None


def normalize_validation_result(result):
    if not result:
        return [], None
    if isinstance(result, tuple):
        errors, focus_name = result
    else:
        errors, focus_name = result, None
    if isinstance(errors, str):
        errors = [errors]
    return list(errors), focus_name or infer_validation_focus(errors)


def set_pending_focus(fields, form_data, focus_name):
    if not focus_name:
        return None
    for field in fields:
        if field.get("name") == focus_name and field.get("advanced"):
            form_data["_advanced_open"] = True
            break
    return focus_name


def interactive_index_by_name(interactive_fields, name):
    if not name:
        return None
    for index, field in enumerate(interactive_fields):
        if field.get("name") == name:
            return index
    return None


def form_data_from_fields(fields):
    return {field["name"]: field.get("value") for field in fields if field.get("name")}


def visible_form_fields(fields):
    return [field for field in fields if field.get("visible", True)]


def interactive_form_fields(visible_fields):
    return [
        field for field in visible_fields if field.get("type") not in ("static_text", "section")
    ]


def sync_field_values(fields, form_data):
    for field in fields:
        if field.get("name") in form_data:
            field["value"] = form_data.get(field["name"])


def advance_radio_value(form_data, field):
    current_value = form_data.get(field.get("name"))
    options = field.get("options", [])
    if current_value in options:
        current_option_index = options.index(current_value)
        form_data[field["name"]] = options[(current_option_index + 1) % len(options)]


def toggle_field_value(form_data, field):
    name = field.get("name")
    form_data[name] = not bool(form_data.get(name))


def first_required_error(visible_fields, form_data):
    for field in visible_fields:
        if field.get("required") and not form_data.get(field["name"]):
            return (
                i18n.get("error_field_required", field=field["label"]),
                field.get("name"),
            )
    return "", None


def node_type_form_fields():
    return [
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


def host_form_fields(
    values=None,
    include_proxy=True,
    advanced_open=False,
    include_context=False,
):
    values = values or {}
    fields = []
    if include_context and values.get("name"):
        fields.append(
            {
                "label": i18n.get("editing_context", name=values.get("name")),
                "type": "static_text",
            }
        )
        if values.get("host"):
            fields.append(
                {
                    "label": i18n.get(
                        "target_context",
                        target=f"{values.get('user', '')}@{values.get('host')}",
                    ),
                    "type": "static_text",
                }
            )

    fields.extend(
        [
            {"label": i18n.get("form_section_basic"), "type": "section"},
            {
                "label": i18n.get("name"),
                "type": "text",
                "name": "name",
                "required": True,
                "value": values.get("name"),
            },
            {
                "label": i18n.get("host_domain"),
                "type": "text",
                "name": "host",
                "required": True,
                "value": values.get("host"),
            },
            {
                "label": i18n.get("port"),
                "type": "text",
                "name": "port",
                "required": True,
                "value": values.get("port", "22"),
            },
            {
                "label": i18n.get("username"),
                "type": "text",
                "name": "user",
                "required": True,
                "value": values.get("user", getpass.getuser()),
            },
            {"label": i18n.get("form_section_auth"), "type": "section"},
            {
                "label": i18n.get("auth_method"),
                "type": "radio",
                "name": "auth",
                "options": ["password", "key", "none"],
                "value": values.get("auth", "password"),
            },
            {
                "label": i18n.get("password"),
                "type": "password",
                "name": "password",
                "required": values.get("auth") == "password",
                "value": values.get("password", ""),
            },
            {
                "label": i18n.get("key_path"),
                "type": "text",
                "name": "id_file",
                "required": values.get("auth") == "key",
                "value": values.get("id_file", ""),
            },
            {
                "label": i18n.get("auth_none_hint"),
                "type": "static_text",
                "auth_visible": "none",
            },
            {
                "label": i18n.get("mfa_secret"),
                "type": "text",
                "name": "mfa_secret",
                "value": values.get("mfa_secret", ""),
            },
            {
                "label": i18n.get("form_section_advanced"),
                "type": "toggle",
                "name": "_advanced_open",
                "value": advanced_open,
            },
        ]
    )

    if include_proxy:
        fields.append(
            {
                "label": i18n.get("proxy_command"),
                "type": "text",
                "name": "proxy_command",
                "advanced": True,
                "value": values.get("proxy_command", ""),
            }
        )

    fields.extend(
        [
            {
                "label": i18n.get("ssh_jump_mode"),
                "type": "radio",
                "name": "ssh_jump_mode",
                "options": ["default", "shell", "tunnel"],
                "advanced": True,
                "value": values.get("ssh_jump_mode", "default"),
            },
            {
                "label": i18n.get("transfer_jump_mode"),
                "type": "radio",
                "name": "transfer_jump_mode",
                "options": ["default", "tunnel", "relay"],
                "advanced": True,
                "value": values.get("transfer_jump_mode", "default"),
            },
            {"label": i18n.get("save"), "type": "button"},
            {"label": i18n.get("cancel"), "type": "button", "name": "cancel"},
        ]
    )
    return fields


def group_form_fields(name=""):
    return [
        {"label": i18n.get("form_section_basic"), "type": "section"},
        {
            "label": i18n.get("name"),
            "type": "text",
            "name": "name",
            "required": True,
            "value": name,
        },
        {"label": i18n.get("save"), "type": "button"},
        {"label": i18n.get("cancel"), "type": "button", "name": "cancel"},
    ]


def clean_form_data(form_data):
    return {
        key: value for key, value in form_data.items() if not str(key).startswith("_")
    }


def apply_dynamic_visibility(fields, form_data):
    auth_method = form_data.get("auth")
    advanced_open = bool(form_data.get("_advanced_open"))
    auth_fields = {"password": "password", "id_file": "key"}
    for field in fields:
        name = field.get("name")
        if auth_method:
            if name in auth_fields:
                field["visible"] = field["required"] = auth_method == auth_fields[name]
            elif field.get("auth_visible") is not None:
                allowed = field.get("auth_visible")
                if isinstance(allowed, str):
                    allowed = {allowed}
                field["visible"] = auth_method in allowed
        if field.get("advanced"):
            field["visible"] = advanced_open
    return fields


def host_node_from_form(final_data):
    data = clean_form_data(final_data)
    port = normalize_port(data.get("port"))
    node = {
        "type": "host",
        "name": data["name"],
        "host": data["host"],
        "user": data["user"],
        "password": data.get("password", ""),
        "id_file": data.get("id_file", ""),
        "mfa_secret": data.get("mfa_secret", ""),
    }
    if port != DEFAULT_PORT:
        node["port"] = port
    for key in ("ssh_jump_mode", "transfer_jump_mode"):
        if data.get(key) != "default":
            node[key] = data.get(key)
    if data.get("proxy_command"):
        node["proxy_command"] = data.get("proxy_command")
    return node


def group_node_from_form(final_data):
    data = clean_form_data(final_data)
    return {
        "type": "group",
        "name": data["name"],
        "expanded": True,
        "children": [],
    }


def update_data_from_form(final_data):
    data = clean_form_data(final_data)
    if "port" in data:
        data["port"] = normalize_port(data.get("port"))
    return data
