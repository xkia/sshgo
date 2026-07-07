#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import binascii
import os
import re

from endpoint import (
    DEFAULT_PORT,
    EndpointParseError,
    normalize_port,
    validate_host_address,
)
from i18n import i18n

SSH_JUMP_MODES = frozenset({"shell", "tunnel"})
TRANSFER_JUMP_MODES = frozenset({"tunnel", "relay"})
DEFAULT_SSH_JUMP_MODE = "shell"
DEFAULT_TRANSFER_JUMP_MODE = "tunnel"
DEFAULT_TUI_SCREEN_POLICY = "isolated"
DEFAULT_TERMINAL_TITLE_ENABLED = False
DEFAULT_TERMINAL_TITLE_TARGET = "tab"
DEFAULT_TERMINAL_TITLE_FORMAT = "alias_host"
DEFAULT_TERMINAL_TITLE_SCOPE = "auto"
DEFAULT_RELAY_TEMP_DIR = "/tmp"
TUI_SCREEN_POLICIES = frozenset({"isolated", "private"})
TERMINAL_TITLE_TARGETS = frozenset({"tab", "window", "both"})
TERMINAL_TITLE_FORMATS = frozenset({"alias", "host", "alias_host"})
TERMINAL_TITLE_SCOPES = frozenset({"auto", "always"})
PLACEHOLDER_RE = re.compile(r"{{([A-Za-z_][A-Za-z0-9_]*)}}")
PLACEHOLDER_TOKEN_RE = re.compile(r"{{([^{}]*)}}")
PLACEHOLDER_BRACE_RE = re.compile(r"{{|}}")
PLACEHOLDER_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PLACEHOLDER_NODE_FIELDS = frozenset({"host", "user", "id_file", "proxy_command"})
LANGUAGES = frozenset({"en", "zh"})
CONFIG_BOOL_FIELDS = frozenset({
    "encryption_enabled",
    "import_ssh_config",
    "show_detail_pane",
    "audit_full",
    "use_ssh_agent",
    "strict_host_key_checking",
    "show_recent",
    "recent_expanded",
    "terminal_title_enabled",
})
CONFIG_STRING_FIELDS = frozenset({
    "language",
    "default_ssh_jump_mode",
    "default_transfer_jump_mode",
    "tui_screen_policy",
    "terminal_title_target",
    "terminal_title_format",
    "terminal_title_scope",
    "relay_temp_dir",
})
CONFIG_OPTIONAL_STRING_FIELDS = frozenset({"data_dir", "encryption_salt"})
THEME_FIELDS = frozenset({"highlight_fg", "highlight_bg", "prefix_color"})
THEME_COLORS = frozenset({
    "black",
    "red",
    "green",
    "yellow",
    "blue",
    "magenta",
    "cyan",
    "white",
    "default",
})
ALLOWED_SAVE_KEYS = frozenset({
    "id", "type", "name", "expanded", "children",
    "host", "port", "user", "password", "id_file", "mfa_secret", "use_ssh_agent",
    "ssh_jump_mode", "transfer_jump_mode", "proxy_command",
})

DEFAULT_CONFIG = {
    "encryption_enabled": False,
    "encryption_salt": None,
    "import_ssh_config": True,
    "language": "en",
    "show_detail_pane": True,
    "audit_full": False,
    "use_ssh_agent": False,
    "data_dir": None,
    "strict_host_key_checking": True,
    "show_recent": True,
    "recent_expanded": False,
    "default_ssh_jump_mode": DEFAULT_SSH_JUMP_MODE,
    "default_transfer_jump_mode": DEFAULT_TRANSFER_JUMP_MODE,
    "tui_screen_policy": DEFAULT_TUI_SCREEN_POLICY,
    "terminal_title_enabled": DEFAULT_TERMINAL_TITLE_ENABLED,
    "terminal_title_target": DEFAULT_TERMINAL_TITLE_TARGET,
    "terminal_title_format": DEFAULT_TERMINAL_TITLE_FORMAT,
    "terminal_title_scope": DEFAULT_TERMINAL_TITLE_SCOPE,
    "relay_temp_dir": DEFAULT_RELAY_TEMP_DIR,
    "placeholders": {},
}


def default_config():
    config = dict(DEFAULT_CONFIG)
    config["placeholders"] = dict(DEFAULT_CONFIG["placeholders"])
    return config


def merge_config(raw_config):
    config = default_config()
    config.update(raw_config)
    if isinstance(config.get("placeholders"), dict):
        config["placeholders"] = dict(config["placeholders"])
    return config


def validate_hosts_config(data: dict) -> list[str]:
    """Validate parsed config data. Returns list of warning/error strings."""
    errors = []

    if not isinstance(data, dict):
        errors.append(i18n.get("validate_root_object"))
        return errors

    if "config" not in data:
        errors.append(i18n.get("validate_missing_config"))
    elif not isinstance(data["config"], dict):
        errors.append(i18n.get("validate_config_not_object"))

    raw_config = (
        data.get("config", {})
        if isinstance(data.get("config", {}), dict)
        else {}
    )
    config = merge_config(raw_config)
    _validate_config_schema(raw_config, errors)
    placeholders = _validate_placeholders(
        raw_config.get("placeholders"),
        errors,
    )
    _validate_encryption_salt(raw_config, data.get("hosts", []), errors)

    default_ssh_jump_mode = config.get("default_ssh_jump_mode")
    if default_ssh_jump_mode not in SSH_JUMP_MODES:
        errors.append(
            i18n.get(
                "validate_invalid_ssh_jump_mode",
                mode=default_ssh_jump_mode,
            )
        )

    default_transfer_jump_mode = config.get("default_transfer_jump_mode")
    if default_transfer_jump_mode not in TRANSFER_JUMP_MODES:
        errors.append(
            i18n.get(
                "validate_invalid_transfer_jump_mode",
                mode=default_transfer_jump_mode,
            )
        )

    tui_screen_policy = config.get("tui_screen_policy")
    if (
        not isinstance(tui_screen_policy, str)
        or tui_screen_policy not in TUI_SCREEN_POLICIES
    ):
        errors.append(
            i18n.get(
                "validate_invalid_tui_screen_policy",
                policy=tui_screen_policy,
            )
        )

    terminal_title_target = config.get("terminal_title_target")
    if (
        not isinstance(terminal_title_target, str)
        or terminal_title_target not in TERMINAL_TITLE_TARGETS
    ):
        errors.append(
            i18n.get(
                "validate_invalid_terminal_title_target",
                target=terminal_title_target,
            )
        )

    terminal_title_format = config.get("terminal_title_format")
    if (
        not isinstance(terminal_title_format, str)
        or terminal_title_format not in TERMINAL_TITLE_FORMATS
    ):
        errors.append(
            i18n.get(
                "validate_invalid_terminal_title_format",
                format=terminal_title_format,
            )
        )

    terminal_title_scope = config.get("terminal_title_scope")
    if (
        not isinstance(terminal_title_scope, str)
        or terminal_title_scope not in TERMINAL_TITLE_SCOPES
    ):
        errors.append(
            i18n.get(
                "validate_invalid_terminal_title_scope",
                scope=terminal_title_scope,
            )
        )

    relay_temp_dir = _resolve_placeholders_for_validation(
        config.get("relay_temp_dir"),
        placeholders,
        errors,
    )
    if not relay_temp_dir or not os.path.isabs(os.path.expanduser(str(relay_temp_dir))):
        errors.append(i18n.get("validate_invalid_relay_temp_dir"))

    if "hosts" not in data:
        errors.append(i18n.get("validate_missing_hosts"))
    elif not isinstance(data["hosts"], list):
        errors.append(i18n.get("validate_hosts_not_array"))
    else:
        _validate_hosts_nodes(
            data["hosts"],
            errors,
            config=config,
            placeholders=placeholders,
            seen_names=set(),
            seen_ids=set(),
        )

    return errors


def _validate_config_schema(config, errors):
    for field in sorted(CONFIG_BOOL_FIELDS):
        if field in config and type(config[field]) is not bool:
            errors.append(
                i18n.get(
                    "validate_invalid_config_type",
                    field=field,
                    expected=i18n.get("validate_type_bool"),
                )
            )

    for field in sorted(CONFIG_STRING_FIELDS):
        if field in config and not isinstance(config[field], str):
            errors.append(
                i18n.get(
                    "validate_invalid_config_type",
                    field=field,
                    expected=i18n.get("validate_type_string"),
                )
            )

    for field in sorted(CONFIG_OPTIONAL_STRING_FIELDS):
        value = config.get(field)
        if field in config and value is not None and not isinstance(value, str):
            errors.append(
                i18n.get(
                    "validate_invalid_config_type",
                    field=field,
                    expected=i18n.get("validate_type_optional_string"),
                )
            )

    language = config.get("language")
    if isinstance(language, str) and language not in LANGUAGES:
        errors.append(i18n.get("validate_invalid_language", lang=language))

    theme = config.get("theme")
    if theme is None:
        return
    if not isinstance(theme, dict):
        errors.append(i18n.get("validate_theme_not_object"))
        return

    for field, color in theme.items():
        if field not in THEME_FIELDS:
            errors.append(i18n.get("validate_unknown_theme_field", field=field))
            continue
        if not isinstance(color, str) or color not in THEME_COLORS:
            errors.append(
                i18n.get(
                    "validate_invalid_theme_color",
                    field=field,
                    color=color,
                )
            )


def _validate_port(port):
    if type(port) is bool:
        return False
    text = str(port).strip()
    if not text:
        return True
    if not text.isdigit():
        return False
    if len(text) > 1 and text.startswith("0"):
        return False
    value = int(port)
    return 1 <= value <= 65535


def _decode_encryption_salt(value):
    decoded = base64.b64decode(
        value.encode("utf-8"),
        altchars=b"-_",
        validate=True,
    )
    if not decoded:
        raise ValueError("empty salt")
    return decoded


def _nodes_have_credentials(nodes):
    if not isinstance(nodes, list):
        return False
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("type") == "host" and (
            node.get("password") or node.get("mfa_secret")
        ):
            return True
        if _nodes_have_credentials(node.get("children")):
            return True
    return False


def _validate_encryption_salt(config, hosts, errors):
    salt = config.get("encryption_salt")
    if isinstance(salt, str):
        try:
            _decode_encryption_salt(salt)
        except (binascii.Error, ValueError):
            errors.append(i18n.get("validate_invalid_encryption_salt"))
    if (
        config.get("encryption_enabled") is True
        and _nodes_have_credentials(hosts)
        and not salt
    ):
        errors.append(i18n.get("validate_missing_encryption_salt"))


def _effective_nested_mode(node, field, parent_mode, config, config_field, default):
    return node.get(field) or parent_mode or config.get(config_field, default)


def _has_host_local_auth(node):
    return bool(
        node.get("password")
        or node.get("id_file")
        or bool(node.get("use_ssh_agent"))
    )


def _validate_placeholders(raw_placeholders, errors):
    if raw_placeholders is None:
        return {}
    if not isinstance(raw_placeholders, dict):
        errors.append(i18n.get("validate_placeholders_not_object"))
        return {}

    placeholders = {}
    for name, value in raw_placeholders.items():
        if not isinstance(name, str) or not PLACEHOLDER_NAME_RE.match(name):
            errors.append(i18n.get("validate_invalid_placeholder_name", name=name))
            continue
        if not isinstance(value, str) or not value.strip():
            errors.append(
                i18n.get("validate_invalid_placeholder_value", name=name)
            )
            continue
        placeholders[name] = value
    return placeholders


def _resolve_placeholders_for_validation(value, placeholders, errors):
    if not isinstance(value, str):
        return value

    matched_spans = []
    seen_errors = set()
    for match in PLACEHOLDER_TOKEN_RE.finditer(value):
        matched_spans.append(match.span())
        name = match.group(1)
        if not PLACEHOLDER_NAME_RE.match(name) and name not in seen_errors:
            errors.append(i18n.get("validate_invalid_placeholder_name", name=name))
            seen_errors.add(name)

    for match in PLACEHOLDER_BRACE_RE.finditer(value):
        if not any(start <= match.start() < end for start, end in matched_spans):
            token = match.group(0)
            errors.append(i18n.get("validate_invalid_placeholder_name", name=token))

    seen_missing = set()

    def replace(match):
        name = match.group(1)
        if name not in placeholders:
            if name not in seen_missing:
                errors.append(i18n.get("validate_unknown_placeholder", name=name))
                seen_missing.add(name)
            return match.group(0)
        return placeholders[name]

    return PLACEHOLDER_RE.sub(replace, value)


def _validate_hosts_nodes(
    nodes: list,
    errors: list,
    path: str = "hosts",
    config=None,
    placeholders=None,
    seen_names=None,
    seen_ids=None,
    parent_is_host=False,
    host_parent_depth=0,
    parent_ssh_jump_mode=None,
    parent_transfer_jump_mode=None,
):
    if config is None:
        config = {}
    if placeholders is None:
        placeholders = {}
    if seen_names is None:
        seen_names = set()
    if seen_ids is None:
        seen_ids = set()
    for i, node in enumerate(nodes):
        node_path = f"{path}[{i}]"
        if not isinstance(node, dict):
            errors.append(i18n.get("validate_node_not_object"))
            continue

        unknown_fields = sorted(set(node) - ALLOWED_SAVE_KEYS)
        for field in unknown_fields:
            errors.append(
                i18n.get("validate_unknown_field", path=node_path, field=field)
            )

        node_type = node.get("type")
        if node_type not in ("host", "group"):
            errors.append(
                i18n.get("validate_invalid_type") + f": '{node_type}'"
            )
            continue

        if node_type != "host":
            for field in ("ssh_jump_mode", "transfer_jump_mode", "proxy_command"):
                if field in node:
                    errors.append(
                        i18n.get("validate_mode_field_on_non_host", field=field)
                    )

        name = node.get("name")
        if not name:
            errors.append(i18n.get("validate_missing_name"))
        elif name in seen_names:
            errors.append(i18n.get("validate_duplicate_name", name=name))
        else:
            seen_names.add(name)

        node_id = node.get("id")
        if node_id is not None:
            if not isinstance(node_id, str) or not node_id.strip():
                errors.append(i18n.get("validate_invalid_id", path=node_path))
            elif node_id in seen_ids:
                errors.append(i18n.get("validate_duplicate_id", node_id=node_id))
            else:
                seen_ids.add(node_id)

        if node_type == "host":
            if host_parent_depth > 1 or (host_parent_depth == 1 and not parent_is_host):
                errors.append(
                    i18n.get(
                        "validate_unsupported_nested_host_depth",
                        path=node_path,
                    )
                )

            for field in PLACEHOLDER_NODE_FIELDS - {"host"}:
                if field in node:
                    _resolve_placeholders_for_validation(
                        node.get(field),
                        placeholders,
                        errors,
                    )

            proxy_command = node.get("proxy_command")
            if proxy_command is not None:
                if not isinstance(proxy_command, str) or not proxy_command.strip():
                    errors.append(i18n.get("validate_invalid_proxy_command"))
                if parent_is_host:
                    errors.append(i18n.get("validate_proxy_command_nested"))

            ssh_jump_mode = node.get("ssh_jump_mode")
            if ssh_jump_mode is not None and ssh_jump_mode not in SSH_JUMP_MODES:
                errors.append(
                    i18n.get("validate_invalid_ssh_jump_mode", mode=ssh_jump_mode)
                )

            transfer_jump_mode = node.get("transfer_jump_mode")
            if (
                transfer_jump_mode is not None
                and transfer_jump_mode not in TRANSFER_JUMP_MODES
            ):
                errors.append(
                    i18n.get(
                        "validate_invalid_transfer_jump_mode",
                        mode=transfer_jump_mode,
                    )
                )
            elif (
                transfer_jump_mode == "relay"
                and not parent_is_host
                and not node.get("children")
            ):
                errors.append(i18n.get("validate_relay_requires_jump"))

            effective_ssh_jump_mode = _effective_nested_mode(
                node,
                "ssh_jump_mode",
                parent_ssh_jump_mode,
                config,
                "default_ssh_jump_mode",
                DEFAULT_SSH_JUMP_MODE,
            )
            effective_transfer_jump_mode = _effective_nested_mode(
                node,
                "transfer_jump_mode",
                parent_transfer_jump_mode,
                config,
                "default_transfer_jump_mode",
                DEFAULT_TRANSFER_JUMP_MODE,
            )

            host_val = _resolve_placeholders_for_validation(
                node.get("host"),
                placeholders,
                errors,
            )
            if not host_val:
                errors.append(i18n.get("validate_missing_host"))
            try:
                host_part = validate_host_address(host_val)
            except EndpointParseError:
                errors.append(i18n.get("validate_invalid_host_endpoint", host=host_val))
            else:
                if not host_part:
                    errors.append(i18n.get("validate_empty_hostname"))

            port_part = normalize_port(node.get("port"))
            if not _validate_port(port_part):
                errors.append(i18n.get("validate_invalid_port", port=port_part))

            uses_agent = (
                bool(node.get("use_ssh_agent"))
                if node.get("use_ssh_agent") is not None
                else bool(config.get("use_ssh_agent", False))
            )
            jump_target_agent_only_modes = []
            if parent_is_host and uses_agent and not _has_host_local_auth(node):
                if effective_ssh_jump_mode == "shell":
                    jump_target_agent_only_modes.append("ssh_jump_mode=shell")
                if effective_transfer_jump_mode == "relay":
                    jump_target_agent_only_modes.append("transfer_jump_mode=relay")

            if jump_target_agent_only_modes:
                errors.append(
                    i18n.get(
                        "validate_missing_jump_target_auth",
                        modes=", ".join(jump_target_agent_only_modes),
                    )
                )
            elif not node.get("password") and not node.get("id_file") and not uses_agent:
                errors.append(i18n.get("validate_missing_auth"))

        if node_type == "group" or node.get("children"):
            children = node.get("children")
            if children is not None:
                if not isinstance(children, list):
                    errors.append(i18n.get("validate_children_not_array"))
                else:
                    _validate_hosts_nodes(
                        children,
                        errors,
                        f"{node_path}.children",
                        config=config,
                        placeholders=placeholders,
                        seen_names=seen_names,
                        seen_ids=seen_ids,
                        parent_is_host=node_type == "host",
                        host_parent_depth=(
                            host_parent_depth + 1
                            if node_type == "host"
                            else host_parent_depth
                        ),
                        parent_ssh_jump_mode=(
                            node.get("ssh_jump_mode")
                            if node_type == "host"
                            else parent_ssh_jump_mode
                        ),
                        parent_transfer_jump_mode=(
                            node.get("transfer_jump_mode")
                            if node_type == "host"
                            else parent_transfer_jump_mode
                        ),
                    )
