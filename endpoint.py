#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import ipaddress

DEFAULT_PORT = "22"


class EndpointParseError(ValueError):
    pass


def validate_host_address(value):
    text = str(value or "").strip()
    if not text:
        return ""

    if text.startswith("[") or text.endswith("]"):
        raise EndpointParseError("host must not use endpoint brackets")

    if ":" in text:
        try:
            address = ipaddress.ip_address(text)
        except ValueError as e:
            raise EndpointParseError("invalid host address") from e
        if address.version != 6:
            raise EndpointParseError("invalid host address")

    return text


def normalize_port(value=None, default_port=DEFAULT_PORT):
    if value is None:
        return str(default_port)
    text = str(value).strip()
    return text if text else str(default_port)


def host_needs_brackets(host):
    value = str(host or "")
    return ":" in value and not (value.startswith("[") and value.endswith("]"))


def format_endpoint(host, port=DEFAULT_PORT, default_port=DEFAULT_PORT, include_default=True):
    host = str(host or "")
    port = str(port or default_port)
    if not host:
        return f":{port}" if include_default or port != str(default_port) else ""

    display_host = f"[{host}]" if host_needs_brackets(host) else host
    if include_default or port != str(default_port):
        return f"{display_host}:{port}"
    return host


def format_proxy_jump_endpoint(host, port=DEFAULT_PORT, default_port=DEFAULT_PORT):
    host = str(host or "")
    port = str(port or default_port)
    display_host = f"[{host}]" if host_needs_brackets(host) else host
    if port != str(default_port):
        return f"{display_host}:{port}"
    return display_host
