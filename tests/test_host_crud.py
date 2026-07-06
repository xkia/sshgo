import unittest

import host_crud


class HostCrudTests(unittest.TestCase):
    def test_apply_update_data_normalizes_port_modes_proxy_and_auth(self):
        node = {
            "type": "host",
            "name": "target",
            "host": "old.example.com",
            "port": "2222",
            "proxy_command": "nc %h %p",
            "ssh_jump_mode": "tunnel",
            "transfer_jump_mode": "relay",
            "password": "old-pass",
            "id_file": "/tmp/old-key",
        }

        host_crud.apply_update_data_to_node(
            node,
            {
                "host": "new.example.com",
                "port": "22",
                "proxy_command": "  ssh bastion nc %h %p  ",
                "ssh_jump_mode": "default",
                "transfer_jump_mode": "",
                "auth": "key",
                "id_file": "/tmp/new-key",
                "password": "ignored",
            },
        )

        self.assertEqual(node["host"], "new.example.com")
        self.assertNotIn("port", node)
        self.assertEqual(node["proxy_command"], "ssh bastion nc %h %p")
        self.assertNotIn("ssh_jump_mode", node)
        self.assertNotIn("transfer_jump_mode", node)
        self.assertEqual(node["id_file"], "/tmp/new-key")
        self.assertEqual(node["password"], "")

    def test_apply_update_data_drops_proxy_for_nested_host(self):
        node = {
            "type": "host",
            "name": "target",
            "host": "target.internal",
            "proxy_command": "nc %h %p",
        }

        host_crud.apply_update_data_to_node(
            node,
            {"proxy_command": "new proxy"},
            is_nested_host=True,
        )

        self.assertNotIn("proxy_command", node)

    def test_build_add_candidate_hosts_copies_candidate(self):
        hosts = [{"type": "group", "name": "parent", "children": []}]
        node_data = {"type": "host", "name": "child", "host": "child.example.com"}

        candidate_hosts = host_crud.build_add_candidate_hosts(
            hosts,
            node_data,
            parent_name="parent",
        )
        node_data["name"] = "mutated"

        child = candidate_hosts[0]["children"][0]
        self.assertEqual(child["name"], "child")

    def test_add_node_to_tree_sets_nested_runtime_parent(self):
        hosts = []
        parent = {"type": "host", "name": "jump", "children": []}
        child = {
            "type": "host",
            "name": "target",
            "proxy_command": "nc %h %p",
        }

        host_crud.add_node_to_tree(
            hosts,
            child,
            parent_node=parent,
            is_nested_host=True,
        )

        self.assertEqual(parent["children"], [child])
        self.assertIs(child["nest_parent"], parent)
        self.assertNotIn("proxy_command", child)

    def test_delete_node_from_parent_returns_status(self):
        parent_list = [{"name": "a"}, {"name": "b"}]

        self.assertTrue(host_crud.delete_node_from_parent(parent_list, 0))
        self.assertEqual(parent_list, [{"name": "b"}])
        self.assertFalse(host_crud.delete_node_from_parent(None, 0))
        self.assertFalse(host_crud.delete_node_from_parent(parent_list, -1))


if __name__ == "__main__":
    unittest.main()
