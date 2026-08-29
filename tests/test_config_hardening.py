import unittest

from web_monitor import ConfigurationError, MonitorConfig


class ConfigHardeningTests(unittest.TestCase):
    def test_target_url_rejects_embedded_credentials(self):
        with self.assertRaises(ConfigurationError):
            MonitorConfig.from_mapping({
                "target_url": "https://user:secret@example.com/page",
                "css_selector": "body",
            })

    def test_numeric_fields_reject_boolean_and_non_finite_values(self):
        cases = (
            ("check_interval_seconds", True),
            ("request_timeout_seconds", "nan"),
            ("backoff_seconds", "inf"),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value), self.assertRaises(ConfigurationError):
                MonitorConfig.from_mapping({
                    "target_url": "https://example.com/",
                    "css_selector": "body",
                    field: value,
                })

        with self.assertRaises(ConfigurationError):
            MonitorConfig.from_mapping({
                "target_url": "https://example.com/",
                "css_selector": "body",
                "notification": {"timeout_seconds": float("inf")},
            })


if __name__ == "__main__":
    unittest.main()
