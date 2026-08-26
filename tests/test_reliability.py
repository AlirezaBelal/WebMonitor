import json
import tempfile
import unittest
from pathlib import Path

import requests

from web_monitor import MonitorConfig, MonitorError, WebMonitor


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

    def get(self, _url, **_kwargs):
        return self.responses.pop(0)


class ReliabilityTests(unittest.TestCase):
    def test_notification_failure_does_not_commit_changed_digest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            config = MonitorConfig.from_mapping(
                {
                    "name": "docs",
                    "target_url": "https://example.com/docs",
                    "css_selector": "main",
                    "state_file": str(state_path),
                    "max_attempts": 1,
                }
            )
            notifications = []
            session = FakeSession(
                [
                    FakeResponse("<main>before</main>"),
                    FakeResponse("<main>after</main>"),
                    FakeResponse("<main>after</main>"),
                ]
            )
            monitor = WebMonitor(
                config,
                session=session,
                notifier=lambda _title, _message: None,
            )

            self.assertEqual(monitor.check_once().status, "baseline")
            baseline_digest = json.loads(
                state_path.read_text(encoding="utf-8")
            )["sha256"]

            def fail_notification(_title, _message):
                raise RuntimeError("delivery unavailable")

            monitor.notifier = fail_notification
            with self.assertRaises(MonitorError) as context:
                monitor.check_once()
            self.assertEqual(str(context.exception), "Notification delivery failed")
            self.assertEqual(
                json.loads(state_path.read_text(encoding="utf-8"))["sha256"],
                baseline_digest,
            )

            monitor.notifier = lambda title, message: notifications.append((title, message))
            self.assertEqual(monitor.check_once().status, "changed")
            self.assertEqual(len(notifications), 1)
            self.assertNotEqual(
                json.loads(state_path.read_text(encoding="utf-8"))["sha256"],
                baseline_digest,
            )


if __name__ == "__main__":
    unittest.main()
