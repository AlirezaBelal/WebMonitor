import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class MutablePageHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        self.server.request_counts[path] = self.server.request_counts.get(path, 0) + 1

        remaining = self.server.failures_remaining.get(path, 0)
        if remaining > 0:
            self.server.failures_remaining[path] = remaining - 1
            body = b"temporary failure"
            self.send_response(503)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        page_html = self.server.pages.get(path)
        if page_html is None:
            body = b"not found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        body = page_html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        self.server.webhook_events.append({"path": path, "payload": payload})
        self.send_response(204)
        self.end_headers()

    def log_message(self, _format, *args):
        return


class CliIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), MutablePageHandler)
        self.server.pages = {
            "/single": '<main><div id="watch">initial value</div></main>',
            "/alpha": '<main><div id="alpha">alpha one</div></main>',
            "/beta": '<main><div id="beta">beta one</div></main>',
        }
        self.server.failures_remaining = {}
        self.server.request_counts = {}
        self.server.webhook_events = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _write_single_config(self, directory: Path) -> Path:
        config_path = directory / "single.json"
        payload = {
            "target_url": f"http://127.0.0.1:{self.server.server_port}/single",
            "css_selector": "#watch",
            "comparison_mode": "text",
            "check_interval_seconds": 1,
            "request_timeout_seconds": 3,
            "max_attempts": 2,
            "backoff_seconds": 0.01,
            "state_file": str(directory / "single-state.json"),
            "user_agent": "WebMonitor-E2E/1.0",
            "notification": {
                "title": "E2E change",
                "message": "Local fixture changed",
            },
        }
        config_path.write_text(json.dumps(payload), encoding="utf-8")
        return config_path

    def _write_multi_config(self, directory: Path, alpha_path: str = "/alpha") -> Path:
        config_path = directory / "multi.json"
        payload = {
            "check_interval_seconds": 1,
            "request_timeout_seconds": 3,
            "max_attempts": 3,
            "backoff_seconds": 0.01,
            "health_file": str(directory / "health.json"),
            "user_agent": "WebMonitor-E2E/1.0",
            "targets": [
                {
                    "name": "alpha",
                    "target_url": f"http://127.0.0.1:{self.server.server_port}{alpha_path}",
                    "css_selector": "#alpha",
                    "state_file": str(directory / "alpha-state.json"),
                    "notification": {
                        "backend": "console",
                        "title": "Alpha change",
                        "message": "alpha changed",
                    },
                },
                {
                    "name": "beta",
                    "target_url": f"http://127.0.0.1:{self.server.server_port}/beta",
                    "css_selector": "#beta",
                    "state_file": str(directory / "beta-state.json"),
                    "notification": {
                        "backend": "webhook",
                        "webhook_url_env": "WEBMONITOR_E2E_WEBHOOK_URL",
                        "title": "Beta change",
                        "message": "beta changed",
                    },
                },
            ],
        }
        config_path.write_text(json.dumps(payload), encoding="utf-8")
        return config_path

    def _run_once(
        self,
        config_path: Path,
        extra_env=None,
    ) -> subprocess.CompletedProcess:
        environment = os.environ.copy()
        if extra_env:
            environment.update(extra_env)
        return subprocess.run(
            [
                sys.executable,
                "main.py",
                "--config",
                str(config_path),
                "--once",
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
            env=environment,
        )

    def _webhook_environment(self):
        return {
            "WEBMONITOR_E2E_WEBHOOK_URL": (
                f"http://127.0.0.1:{self.server.server_port}/hook"
            )
        }

    def test_legacy_single_target_cli_remains_compatible(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            config_path = self._write_single_config(directory)
            state_path = directory / "single-state.json"

            baseline = self._run_once(config_path)
            self.assertEqual(baseline.returncode, 0, baseline.stderr)
            self.assertIn("Status: baseline; matched elements: 1", baseline.stdout)
            self.assertNotIn("E2E change", baseline.stdout)

            state_text = state_path.read_text(encoding="utf-8")
            self.assertNotIn("initial value", state_text)

            self.server.pages["/single"] = '<main><div id="watch">updated value</div></main>'
            changed = self._run_once(config_path)
            self.assertEqual(changed.returncode, 0, changed.stderr)
            self.assertIn("E2E change: Local fixture changed", changed.stdout)
            self.assertIn("Status: changed; matched elements: 1", changed.stdout)

    def test_multi_target_cli_retries_webhook_and_health_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            config_path = self._write_multi_config(directory)
            env = self._webhook_environment()
            health_path = directory / "health.json"
            self.server.failures_remaining["/alpha"] = 2

            baseline = self._run_once(config_path, env)
            self.assertEqual(baseline.returncode, 0, baseline.stderr)
            self.assertIn("[alpha] Status: baseline; matched elements: 1", baseline.stdout)
            self.assertIn("[beta] Status: baseline; matched elements: 1", baseline.stdout)
            self.assertEqual(self.server.request_counts["/alpha"], 3)
            self.assertEqual(self.server.request_counts["/beta"], 1)
            self.assertEqual(self.server.webhook_events, [])

            baseline_health = json.loads(health_path.read_text(encoding="utf-8"))
            self.assertTrue(baseline_health["healthy"])
            self.assertEqual(baseline_health["targets_total"], 2)
            self.assertNotIn(
                f"http://127.0.0.1:{self.server.server_port}",
                health_path.read_text(encoding="utf-8"),
            )

            unchanged = self._run_once(config_path, env)
            self.assertEqual(unchanged.returncode, 0, unchanged.stderr)
            self.assertIn("[alpha] Status: unchanged; matched elements: 1", unchanged.stdout)
            self.assertIn("[beta] Status: unchanged; matched elements: 1", unchanged.stdout)

            self.server.pages["/beta"] = '<main><div id="beta">beta two</div></main>'
            changed = self._run_once(config_path, env)
            self.assertEqual(changed.returncode, 0, changed.stderr)
            self.assertIn("[alpha] Status: unchanged; matched elements: 1", changed.stdout)
            self.assertIn("[beta] Status: changed; matched elements: 1", changed.stdout)
            self.assertEqual(len(self.server.webhook_events), 1)

            event = self.server.webhook_events[0]
            self.assertEqual(event["path"], "/hook")
            self.assertEqual(
                event["payload"],
                {
                    "event": "webmonitor.change",
                    "target": "beta",
                    "title": "Beta change",
                    "message": "beta changed",
                },
            )

            alpha_state = (directory / "alpha-state.json").read_text(encoding="utf-8")
            beta_state = (directory / "beta-state.json").read_text(encoding="utf-8")
            self.assertNotIn("alpha one", alpha_state)
            self.assertNotIn("beta two", beta_state)
            self.assertNotEqual(
                json.loads(alpha_state)["monitor_key"],
                json.loads(beta_state)["monitor_key"],
            )

            changed_health = json.loads(health_path.read_text(encoding="utf-8"))
            self.assertTrue(changed_health["healthy"])
            statuses = {item["name"]: item["status"] for item in changed_health["targets"]}
            self.assertEqual(statuses["alpha"], "unchanged")
            self.assertEqual(statuses["beta"], "changed")

    def test_one_target_failure_does_not_block_other_targets_and_marks_health(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            config_path = self._write_multi_config(directory, alpha_path="/missing")

            result = self._run_once(config_path, self._webhook_environment())

            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "[alpha] Check failed: HTTP request failed with status 404",
                result.stderr,
            )
            self.assertIn("[beta] Status: baseline; matched elements: 1", result.stdout)
            self.assertTrue((directory / "beta-state.json").exists())
            self.assertFalse((directory / "alpha-state.json").exists())

            health = json.loads((directory / "health.json").read_text(encoding="utf-8"))
            self.assertFalse(health["healthy"])
            self.assertEqual(health["checks_failed"], 1)
            statuses = {item["name"]: item["status"] for item in health["targets"]}
            self.assertEqual(statuses["alpha"], "error")
            self.assertEqual(statuses["beta"], "baseline")


if __name__ == "__main__":
    unittest.main()
