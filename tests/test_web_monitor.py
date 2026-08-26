import json
import tempfile
import unittest
from pathlib import Path

import requests

from web_monitor import (
    ConfigurationError,
    MonitorConfig,
    MonitorError,
    SnapshotStore,
    WebMonitor,
)


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(response=response)


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class MonitorConfigTests(unittest.TestCase):
    def test_accepts_valid_configuration(self):
        config = MonitorConfig.from_mapping(
            {
                "target_url": "https://example.com/page",
                "css_selector": ".item",
                "check_interval_seconds": 60,
                "request_timeout_seconds": 5,
            }
        )

        self.assertEqual(config.target_url, "https://example.com/page")
        self.assertEqual(config.css_selector, ".item")
        self.assertEqual(config.comparison_mode, "text")

    def test_rejects_non_http_url_and_invalid_numbers(self):
        with self.assertRaises(ConfigurationError):
            MonitorConfig.from_mapping(
                {"target_url": "file:///tmp/page.html", "css_selector": "body"}
            )

        with self.assertRaises(ConfigurationError):
            MonitorConfig.from_mapping(
                {
                    "target_url": "https://example.com",
                    "css_selector": "body",
                    "check_interval_seconds": 0,
                }
            )


class WebMonitorTests(unittest.TestCase):
    def _config(self, state_file: str, **overrides):
        payload = {
            "target_url": "https://example.com/monitor",
            "css_selector": ".item",
            "comparison_mode": "text",
            "check_interval_seconds": 60,
            "request_timeout_seconds": 7,
            "state_file": state_file,
            "user_agent": "WebMonitor-Test/1.0",
            "notification": {"title": "Changed", "message": "Content changed"},
        }
        payload.update(overrides)
        return MonitorConfig.from_mapping(payload)

    def test_first_check_creates_baseline_without_notification_or_raw_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = str(Path(temp_dir) / "state.json")
            notifications = []
            session = FakeSession([FakeResponse('<div class="item">private value</div>')])
            monitor = WebMonitor(
                self._config(state_file),
                notifier=lambda title, message: notifications.append((title, message)),
                session=session,
            )

            result = monitor.check_once()

            self.assertEqual(result.status, "baseline")
            self.assertEqual(result.matched_elements, 1)
            self.assertEqual(notifications, [])
            state_text = Path(state_file).read_text(encoding="utf-8")
            self.assertNotIn("private value", state_text)
            self.assertEqual(len(json.loads(state_text)["sha256"]), 64)

    def test_unchanged_check_does_not_notify(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = str(Path(temp_dir) / "state.json")
            notifications = []
            session = FakeSession(
                [
                    FakeResponse('<div class="item">same</div>'),
                    FakeResponse('<div class="item">same</div>'),
                ]
            )
            monitor = WebMonitor(
                self._config(state_file),
                notifier=lambda title, message: notifications.append((title, message)),
                session=session,
            )

            self.assertEqual(monitor.check_once().status, "baseline")
            self.assertEqual(monitor.check_once().status, "unchanged")
            self.assertEqual(notifications, [])

    def test_changed_check_updates_state_and_notifies_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = str(Path(temp_dir) / "state.json")
            notifications = []
            session = FakeSession(
                [
                    FakeResponse('<div class="item">before</div>'),
                    FakeResponse('<div class="item">after</div>'),
                ]
            )
            monitor = WebMonitor(
                self._config(state_file),
                notifier=lambda title, message: notifications.append((title, message)),
                session=session,
            )

            monitor.check_once()
            result = monitor.check_once()

            self.assertEqual(result.status, "changed")
            self.assertEqual(notifications, [("Changed", "Content changed")])

    def test_html_mode_detects_attribute_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = str(Path(temp_dir) / "state.json")
            session = FakeSession(
                [
                    FakeResponse('<a class="item" href="/before">Label</a>'),
                    FakeResponse('<a class="item" href="/after">Label</a>'),
                ]
            )
            monitor = WebMonitor(
                self._config(state_file, comparison_mode="html"),
                session=session,
            )

            monitor.check_once()
            self.assertEqual(monitor.check_once().status, "changed")

    def test_selector_must_match_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            monitor = WebMonitor(
                self._config(str(Path(temp_dir) / "state.json")),
                session=FakeSession([FakeResponse("<main>content</main>")]),
            )

            with self.assertRaises(MonitorError) as context:
                monitor.check_once()

            self.assertIn("selector", str(context.exception).lower())

    def test_request_timeout_and_user_agent_are_applied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = FakeSession([FakeResponse('<div class="item">ok</div>')])
            monitor = WebMonitor(
                self._config(str(Path(temp_dir) / "state.json")),
                session=session,
            )

            monitor.check_once()

            _url, kwargs = session.calls[0]
            self.assertEqual(kwargs["timeout"], 7.0)
            self.assertEqual(kwargs["headers"]["User-Agent"], "WebMonitor-Test/1.0")

    def test_http_error_message_does_not_echo_target_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._config(str(Path(temp_dir) / "state.json"))
            session = FakeSession([FakeResponse("error", status_code=503)])
            monitor = WebMonitor(config, session=session)

            with self.assertRaises(MonitorError) as context:
                monitor.check_once()

            message = str(context.exception)
            self.assertIn("503", message)
            self.assertNotIn(config.target_url, message)

    def test_invalid_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            state_path.write_text("not-json", encoding="utf-8")

            with self.assertRaises(MonitorError):
                SnapshotStore(str(state_path)).load_digest()


if __name__ == "__main__":
    unittest.main()
