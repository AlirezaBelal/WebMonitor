import json
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
            "user_agent": "WebMonitor-E2E/1.0",
            "targets": [
                {
                    "name": "alpha",
                    "target_url": f"http://127.0.0.1:{self.server.server_port}{alpha_path}",
                    "css_selector": "#alpha",
                    "state_file": str(directory / "alpha-state.json"),
                    "notification": {
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
                        "title": "Beta change",
                        "message": "beta changed",
                    },
                },
            ],
        }
        config_path.write_text(json.dumps(payload), encoding="utf-8")
        return config_path

    def _run_once(self, config_path: Path) -> subprocess.CompletedProcess:
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
        )

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

    def test_multi_target_cli_retries_and_tracks_state_independently(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            config_path = self._write_multi_config(directory)
            self.server.failures_remaining["/alpha"] = 2

            baseline = self._run_once(config_path)
            self.assertEqual(baseline.returncode, 0, baseline.stderr)
            self.assertIn("[alpha] Status: baseline; matched elements: 1", baseline.stdout)
            self.assertIn("[beta] Status: baseline; matched elements: 1", baseline.stdout)
            self.assertEqual(self.server.request_counts["/alpha"], 3)
            self.assertEqual(self.server.request_counts["/beta"], 1)

            unchanged = self._run_once(config_path)
            self.assertEqual(unchanged.returncode, 0, unchanged.stderr)
            self.assertIn("[alpha] Status: unchanged; matched elements: 1", unchanged.stdout)
            self.assertIn("[beta] Status: unchanged; matched elements: 1", unchanged.stdout)

            self.server.pages["/beta"] = '<main><div id="beta">beta two</div></main>'
            changed = self._run_once(config_path)
            self.assertEqual(changed.returncode, 0, changed.stderr)
            self.assertIn("[alpha] Status: unchanged; matched elements: 1", changed.stdout)
            self.assertIn("[beta] Beta change: beta changed", changed.stdout)
            self.assertIn("[beta] Status: changed; matched elements: 1", changed.stdout)
            self.assertNotIn("Alpha change", changed.stdout)

            alpha_state = (directory / "alpha-state.json").read_text(encoding="utf-8")
            beta_state = (directory / "beta-state.json").read_text(encoding="utf-8")
            self.assertNotIn("alpha one", alpha_state)
            self.assertNotIn("beta two", beta_state)
            self.assertNotEqual(
                json.loads(alpha_state)["monitor_key"],
                json.loads(beta_state)["monitor_key"],
            )

    def test_one_target_failure_does_not_block_other_targets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            config_path = self._write_multi_config(directory, alpha_path="/missing")

            result = self._run_once(config_path)

            self.assertEqual(result.returncode, 1)
            self.assertIn("[alpha] Check failed: HTTP request failed with status 404", result.stderr)
            self.assertIn("[beta] Status: baseline; matched elements: 1", result.stdout)
            self.assertTrue((directory / "beta-state.json").exists())
            self.assertFalse((directory / "alpha-state.json").exists())


if __name__ == "__main__":
    unittest.main()
