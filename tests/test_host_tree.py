import unittest

import host_tree


class HostTreeTests(unittest.TestCase):
    def _tree(self):
        return [
            {
                "id": "group-1",
                "type": "group",
                "name": "group",
                "children": [
                    {
                        "id": "jump-1",
                        "type": "host",
                        "name": "jump",
                        "host": "jump.example.com",
                        "children": [
                            {
                                "id": "target-1",
                                "type": "host",
                                "name": "target",
                                "host": "target.example.com",
                            }
                        ],
                    }
                ],
            },
            {
                "id": "direct-1",
                "type": "host",
                "name": "direct",
                "host": "direct.example.com",
            },
        ]

    def test_traverse_find_replace_and_parent_lookup(self):
        nodes = self._tree()

        self.assertEqual(
            [node["name"] for node in host_tree.traverse_all(nodes)],
            ["group", "jump", "target", "direct"],
        )
        self.assertEqual(host_tree.find_node(nodes, name="target")["id"], "target-1")
        self.assertEqual(host_tree.find_node(nodes, node_id="direct-1")["name"], "direct")

        replacement = {
            "id": "target-1",
            "type": "host",
            "name": "renamed",
            "host": "target.example.com",
        }
        self.assertTrue(host_tree.replace_node(nodes, replacement, node_id="target-1"))
        self.assertEqual(host_tree.find_node(nodes, node_id="target-1")["name"], "renamed")

        node, parent_list, index = host_tree.find_node_and_parent(
            nodes,
            node_id="target-1",
        )
        self.assertEqual(node["name"], "renamed")
        self.assertIs(parent_list, nodes[0]["children"][0]["children"])
        self.assertEqual(index, 0)

    def test_contains_hosts_and_potential_parents(self):
        nodes = self._tree()
        empty_group = {"type": "group", "name": "empty", "children": []}

        self.assertTrue(host_tree.contains_hosts(nodes[0]))
        self.assertFalse(host_tree.contains_hosts(empty_group))
        self.assertEqual(
            [node["name"] for node in host_tree.potential_parents(nodes)],
            ["group", "jump", "target", "direct"],
        )

    def test_ensure_node_ids_assigns_missing_blank_invalid_and_duplicate_saved_nodes(self):
        nodes = [
            {
                "id": "dup",
                "type": "host",
                "name": "one",
                "host": "one.example.com",
            },
            {
                "id": "dup",
                "type": "host",
                "name": "two",
                "host": "two.example.com",
            },
            {
                "id": "",
                "type": "host",
                "name": "blank",
                "host": "blank.example.com",
            },
            {
                "id": "   ",
                "type": "host",
                "name": "whitespace",
                "host": "whitespace.example.com",
            },
            {
                "id": 123,
                "type": "host",
                "name": "non-string",
                "host": "non-string.example.com",
            },
            {
                "type": "host",
                "name": "imported",
                "host": "imported.example.com",
                "source": "ssh_config",
                "children": [
                    {
                        "type": "host",
                        "name": "imported-child",
                        "host": "imported-child.example.com",
                    }
                ],
            },
        ]
        generated = iter(["new-id", "blank-id", "whitespace-id", "non-string-id"])

        changed = host_tree.ensure_node_ids(nodes, lambda: next(generated))

        self.assertTrue(changed)
        self.assertEqual(nodes[0]["id"], "dup")
        self.assertEqual(nodes[1]["id"], "new-id")
        self.assertEqual(nodes[2]["id"], "blank-id")
        self.assertEqual(nodes[3]["id"], "whitespace-id")
        self.assertEqual(nodes[4]["id"], "non-string-id")
        self.assertNotIn("id", nodes[5])
        self.assertNotIn("id", nodes[5]["children"][0])

    def test_rebuild_nest_parents_sets_runtime_links(self):
        nodes = self._tree()

        host_tree.rebuild_nest_parents(nodes)

        jump = host_tree.find_node(nodes, node_id="jump-1")
        target = host_tree.find_node(nodes, node_id="target-1")
        direct = host_tree.find_node(nodes, node_id="direct-1")

        self.assertNotIn("nest_parent", jump)
        self.assertIs(target["nest_parent"], jump)
        self.assertEqual(target["_host_ancestor_count"], 1)
        self.assertTrue(target["_direct_parent_is_host"])
        self.assertNotIn("nest_parent", direct)


if __name__ == "__main__":
    unittest.main()
