import copy

from config_validation import DEFAULT_PORT
from endpoint import normalize_port
import host_tree


def candidate_config_data(config, hosts):
    return {
        "config": copy.deepcopy(config),
        "hosts": hosts,
    }


def build_add_candidate_hosts(hosts, node_data, parent_name=None, parent_id=None):
    candidate = copy.deepcopy(node_data)
    if parent_name or parent_id:
        parent = host_tree.find_node(hosts, name=parent_name, node_id=parent_id)
        if parent:
            parent.setdefault("children", []).append(candidate)
        else:
            hosts.append(candidate)
    else:
        hosts.append(candidate)
    return hosts


def apply_update_data_to_node(node, new_data, is_nested_host=False):
    if is_nested_host:
        node.pop("proxy_command", None)

    for key, value in new_data.items():
        if key == "auth":
            continue
        if key == "port":
            port = normalize_port(value)
            if port == DEFAULT_PORT:
                node.pop("port", None)
            else:
                node["port"] = port
            continue
        if key in ("ssh_jump_mode", "transfer_jump_mode"):
            if value in (None, "", "default"):
                node.pop(key, None)
            else:
                node[key] = value
            continue
        if key == "proxy_command":
            if is_nested_host:
                continue
            if value is None or not str(value).strip():
                node.pop(key, None)
            else:
                node[key] = str(value).strip()
            continue
        node[key] = value

    auth_method = new_data.get("auth")
    if auth_method == "password":
        node["password"] = new_data.get("password", "")
        node["id_file"] = ""
    elif auth_method == "key":
        node["id_file"] = new_data.get("id_file", "")
        node["password"] = ""
    elif auth_method == "none":
        node["password"] = ""
        node["id_file"] = ""


def build_update_candidate_hosts(
    hosts,
    current,
    new_data,
    is_nested_host=False,
    node_name=None,
    node_id=None,
):
    current_id = node_id or current.get("id")
    clean_current = host_tree.find_node(
        hosts,
        name=node_name,
        node_id=current_id,
    )
    if not clean_current:
        return None

    candidate = copy.deepcopy(clean_current)
    apply_update_data_to_node(
        candidate,
        new_data,
        is_nested_host=is_nested_host,
    )
    host_tree.replace_node(
        hosts,
        candidate,
        name=node_name,
        node_id=current_id,
    )
    return hosts


def existing_node_ids(hosts):
    return {
        node.get("id")
        for node in host_tree.traverse_all(hosts)
        if isinstance(node.get("id"), str)
    }


def add_node_to_tree(hosts, node_data, parent_node=None, is_nested_host=False):
    if parent_node:
        if is_nested_host:
            node_data.pop("proxy_command", None)
        parent_node.setdefault("children", []).append(node_data)
        if is_nested_host:
            node_data["nest_parent"] = parent_node
    else:
        hosts.append(node_data)


def delete_node_from_parent(parent_list, index):
    if parent_list is None or index == -1:
        return False
    del parent_list[index]
    return True
