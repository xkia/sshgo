from endpoint import DEFAULT_PORT, format_endpoint
from i18n import i18n


def _history_child(record):
    name = record.get("name", "")
    host = record.get("host", "")
    user = record.get("user", "")
    port = record.get("port")
    history_host = record.get("endpoint") or host
    if host and port and not record.get("endpoint"):
        history_host = format_endpoint(
            host,
            port,
            default_port=DEFAULT_PORT,
            include_default=True,
        )
    return {
        "type": "host",
        "name": name,
        "host": history_host,
        "user": user,
        "password": "",
        "id_file": "",
        "mfa_secret": "",
        "source": "history",
    }


def _resolve_recent_child(host_manager, record):
    name = record.get("name", "")
    host = record.get("host", "")
    user = record.get("user", "")
    port = record.get("port")
    node_id = record.get("node_id")

    existing = host_manager.find_host_by_id(node_id)
    if not existing:
        existing = host_manager.find_host_by_alias(name)
    if existing:
        return ("current", existing.get("name", "")), existing.copy()

    current = host_manager.find_host_by_endpoint(host, user, port)
    if current:
        return ("current", current.get("name", "")), current.copy()

    return ("history", name, host, user, port), _history_child(record)


def build_recent_group(host_manager, limit=10):
    if not host_manager.config.get("show_recent", True):
        return None

    recent_records = host_manager.audit.get_history(limit=limit)
    if not recent_records:
        return None

    children = []
    seen_keys = set()
    for record in reversed(recent_records):
        seen_key, child = _resolve_recent_child(host_manager, record)
        if seen_key in seen_keys:
            continue
        seen_keys.add(seen_key)
        children.append(child)

    if not children:
        return None

    return {
        "type": "group",
        "name": i18n.get("recent"),
        "expanded": host_manager.config.get("recent_expanded", False),
        "children": children,
        "source": "recent_group",
    }
