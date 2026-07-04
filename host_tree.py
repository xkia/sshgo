#!/usr/bin/env python3
# -*- coding: utf-8 -*-


def traverse_all(nodes):
    for node in nodes:
        yield node
        if node.get("children"):
            yield from traverse_all(node["children"])


def find_node(nodes, name=None, node_id=None):
    for node in nodes:
        if node_id and node.get("id") == node_id:
            return node
        if name and node.get("name") == name:
            return node
        found = find_node(
            node.get("children", []),
            name=name,
            node_id=node_id,
        )
        if found:
            return found
    return None


def replace_node(nodes, replacement, name=None, node_id=None):
    for index, node in enumerate(nodes):
        if (node_id and node.get("id") == node_id) or (
            name and node.get("name") == name
        ):
            nodes[index] = replacement
            return True
        if replace_node(
            node.get("children", []),
            replacement,
            name=name,
            node_id=node_id,
        ):
            return True
    return False


def find_node_and_parent(nodes, name=None, node_id=None, parent_list=None):
    if not name and not node_id:
        return None, None, -1
    if parent_list is None:
        parent_list = nodes
    for index, node in enumerate(nodes):
        if (node_id and node.get("id") == node_id) or (
            name and node.get("name") == name
        ):
            return node, parent_list, index
        if node.get("children"):
            found, found_parent, found_index = find_node_and_parent(
                node["children"],
                name=name,
                node_id=node_id,
                parent_list=node["children"],
            )
            if found:
                return found, found_parent, found_index
    return None, None, -1


def contains_hosts(node):
    if node.get("type") == "host":
        return True
    for child in node.get("children", []) or []:
        if contains_hosts(child):
            return True
    return False


def potential_parents(nodes):
    return [
        node
        for node in traverse_all(nodes)
        if node.get("type") in ("group", "host")
    ]


def ensure_node_ids(nodes, new_id, seen_ids=None):
    if seen_ids is None:
        seen_ids = set()

    changed = False
    for node in nodes:
        if "ssh_config" in node.get("source", ""):
            continue

        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id.strip() or node_id in seen_ids:
            node_id = new_id()
            node["id"] = node_id
            changed = True
        seen_ids.add(node_id)

        if node.get("children"):
            changed = ensure_node_ids(node["children"], new_id, seen_ids) or changed

    return changed


def rebuild_nest_parents(nodes, host_ancestors=None, direct_parent=None):
    if host_ancestors is None:
        host_ancestors = []

    for node in nodes:
        node_type = node.get("type")
        if node_type == "host":
            node["_host_ancestor_count"] = len(host_ancestors)
            node["_direct_parent_is_host"] = bool(
                direct_parent and direct_parent.get("type") == "host"
            )
            if node["_direct_parent_is_host"]:
                node["nest_parent"] = direct_parent
            else:
                node.pop("nest_parent", None)
            next_host_ancestors = host_ancestors + [node]
        else:
            next_host_ancestors = host_ancestors

        if node.get("children"):
            rebuild_nest_parents(
                node["children"],
                next_host_ancestors,
                node,
            )
