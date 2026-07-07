import unittest

import tui_forms


def _field(fields, name):
    for field in fields:
        if field.get("name") == name:
            return field
    raise AssertionError(f"field not found: {name}")


class TuiFormsTests(unittest.TestCase):
    def test_host_node_omits_default_modes_and_keeps_proxy_when_present(self):
        node = tui_forms.host_node_from_form(
            {
                "name": "demo",
                "host": "example.com",
                "port": "22",
                "user": "deploy",
                "password": "pw",
                "id_file": "",
                "mfa_secret": "",
                "ssh_jump_mode": "default",
                "transfer_jump_mode": "default",
                "proxy_command": "nc %h %p",
                "_advanced_open": True,
            }
        )

        self.assertEqual(node["host"], "example.com")
        self.assertNotIn("port", node)
        self.assertNotIn("ssh_jump_mode", node)
        self.assertNotIn("transfer_jump_mode", node)
        self.assertEqual(node["proxy_command"], "nc %h %p")
        self.assertNotIn("_advanced_open", node)

    def test_host_node_persists_non_default_modes(self):
        node = tui_forms.host_node_from_form(
            {
                "name": "demo",
                "host": "example.com",
                "port": "2222",
                "user": "deploy",
                "ssh_jump_mode": "tunnel",
                "transfer_jump_mode": "relay",
            }
        )

        self.assertEqual(node["ssh_jump_mode"], "tunnel")
        self.assertEqual(node["transfer_jump_mode"], "relay")

    def test_update_data_keeps_host_and_port_separate(self):
        data = tui_forms.update_data_from_form(
            {
                "name": "demo",
                "host": "example.com",
                "port": "2222",
                "_screen_y": 4,
            }
        )

        self.assertEqual(data["host"], "example.com")
        self.assertEqual(data["port"], "2222")
        self.assertNotIn("_screen_y", data)

    def test_host_form_keeps_ipv6_host_and_port_separate(self):
        node = tui_forms.host_node_from_form(
            {
                "name": "ipv6",
                "host": "2001:db8::5",
                "port": "2222",
                "user": "deploy",
            }
        )

        self.assertEqual(node["host"], "2001:db8::5")
        self.assertEqual(node["port"], "2222")

    def test_host_form_auth_required_state_and_proxy_visibility(self):
        password_fields = tui_forms.host_form_fields(
            values={"auth": "password"},
            include_proxy=False,
        )
        key_fields = tui_forms.host_form_fields(
            values={"auth": "key"},
            include_proxy=True,
        )

        self.assertTrue(_field(password_fields, "password")["required"])
        self.assertFalse(_field(password_fields, "id_file")["required"])
        self.assertNotIn(
            "proxy_command",
            [field.get("name") for field in password_fields],
        )
        self.assertFalse(_field(key_fields, "password")["required"])
        self.assertTrue(_field(key_fields, "id_file")["required"])
        self.assertEqual(_field(key_fields, "proxy_command")["advanced"], True)

    def test_dynamic_visibility_tracks_auth_and_advanced_state(self):
        fields = tui_forms.host_form_fields(
            values={"auth": "password"},
            include_proxy=True,
        )

        tui_forms.apply_dynamic_visibility(
            fields,
            {"auth": "password", "_advanced_open": False},
        )
        self.assertTrue(_field(fields, "password")["visible"])
        self.assertFalse(_field(fields, "id_file")["visible"])
        self.assertFalse(_field(fields, "proxy_command")["visible"])

        tui_forms.apply_dynamic_visibility(
            fields,
            {"auth": "key", "_advanced_open": True},
        )
        self.assertFalse(_field(fields, "password")["visible"])
        self.assertTrue(_field(fields, "id_file")["visible"])
        self.assertTrue(_field(fields, "proxy_command")["visible"])

        tui_forms.apply_dynamic_visibility(
            fields,
            {"auth": "none", "_advanced_open": True},
        )
        self.assertFalse(_field(fields, "password")["visible"])
        self.assertFalse(_field(fields, "id_file")["visible"])
        auth_hint = next(
            field for field in fields if field.get("auth_visible") == "none"
        )
        self.assertTrue(auth_hint["visible"])

    def test_group_and_node_type_fields(self):
        group = tui_forms.group_node_from_form({"name": "ops", "_x": 1})
        self.assertEqual(group["type"], "group")
        self.assertEqual(group["children"], [])
        self.assertNotIn("_x", group)

        type_fields = tui_forms.node_type_form_fields()
        self.assertEqual(_field(type_fields, "type")["options"], ["host", "group"])


if __name__ == "__main__":
    unittest.main()
