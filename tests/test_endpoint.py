import unittest

from endpoint import (
    EndpointParseError,
    format_endpoint,
    format_proxy_jump_endpoint,
    normalize_port,
    validate_host_address,
)


class EndpointTests(unittest.TestCase):
    def test_validate_hostname_and_ipv6_host(self):
        self.assertEqual(validate_host_address("example.com"), "example.com")
        self.assertEqual(validate_host_address("2001:db8::1"), "2001:db8::1")

    def test_validate_host_rejects_combined_or_invalid_endpoint(self):
        for value in (
            "example.com:2222",
            "[2001:db8::1]:2222",
            "[2001:db8::1]",
            "foo:bar:baz",
            "2001:db8::zz",
        ):
            with self.subTest(value=value):
                with self.assertRaises(EndpointParseError):
                    validate_host_address(value)

    def test_normalize_port_defaults_empty_values(self):
        self.assertEqual(normalize_port(None), "22")
        self.assertEqual(normalize_port(""), "22")
        self.assertEqual(normalize_port(2222), "2222")

    def test_format_brackets_ipv6_when_port_is_shown(self):
        self.assertEqual(
            format_endpoint("2001:db8::1", "2222"),
            "[2001:db8::1]:2222",
        )
        self.assertEqual(
            format_endpoint("2001:db8::1", "22", include_default=False),
            "2001:db8::1",
        )

    def test_format_proxy_jump_brackets_ipv6_even_without_port(self):
        self.assertEqual(
            format_proxy_jump_endpoint("2001:db8::1"),
            "[2001:db8::1]",
        )
        self.assertEqual(
            format_proxy_jump_endpoint("2001:db8::1", "2222"),
            "[2001:db8::1]:2222",
        )


if __name__ == "__main__":
    unittest.main()
