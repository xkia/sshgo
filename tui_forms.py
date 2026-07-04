#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import getpass

from i18n import i18n


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
        key: value
        for key, value in form_data.items()
        if not str(key).startswith("_")
    }


def apply_dynamic_visibility(fields, form_data):
    auth_method = form_data.get("auth")
    advanced_open = bool(form_data.get("_advanced_open"))
    for field in fields:
        if auth_method:
            if field.get("name") == "password":
                field["visible"] = auth_method == "password"
                field["required"] = auth_method == "password"
            elif field.get("name") == "id_file":
                field["visible"] = auth_method == "key"
                field["required"] = auth_method == "key"
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
    node = {
        "type": "host",
        "name": data["name"],
        "host": f"{data['host']}:{data['port']}",
        "user": data["user"],
        "password": data.get("password", ""),
        "id_file": data.get("id_file", ""),
        "mfa_secret": data.get("mfa_secret", ""),
    }
    if data.get("ssh_jump_mode") != "default":
        node["ssh_jump_mode"] = data.get("ssh_jump_mode")
    if data.get("transfer_jump_mode") != "default":
        node["transfer_jump_mode"] = data.get("transfer_jump_mode")
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
    if "host" in data and "port" in data:
        data["host"] = f"{data['host']}:{data['port']}"
    return data
