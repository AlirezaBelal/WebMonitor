import json
import tempfile
import unittest
from pathlib import Path

from health import HealthRecord, HealthReporter


class HealthReporterTests(unittest.TestCase):
    def test_health_snapshot_is_privacy_safe_and_summarizes_failures(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "health.json"
            reporter = HealthReporter(str(path))
            reporter.write(
                [
                    HealthRecord(
                        name="alpha",
                        status="changed",
                        matched_elements=2,
                    ),
                    HealthRecord(
                        name="beta",
                        status="error",
                        error="HTTP request failed with status 503 after 3 attempt(s)",
                    ),
                ]
            )

            text = path.read_text(encoding="utf-8")
            payload = json.loads(text)

            self.assertFalse(payload["healthy"])
            self.assertEqual(payload["targets_total"], 2)
            self.assertEqual(payload["checks_succeeded"], 1)
            self.assertEqual(payload["checks_failed"], 1)
            self.assertEqual(payload["status_counts"]["changed"], 1)
            self.assertEqual(payload["status_counts"]["error"], 1)
            self.assertNotIn("target_url", text)
            self.assertNotIn("css_selector", text)

    def test_all_successful_records_are_healthy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "health.json"
            HealthReporter(str(path)).write(
                [
                    HealthRecord(name="alpha", status="baseline", matched_elements=1),
                    HealthRecord(name="beta", status="unchanged", matched_elements=1),
                ]
            )

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(payload["healthy"])
            self.assertEqual(payload["checks_failed"], 0)


if __name__ == "__main__":
    unittest.main()
