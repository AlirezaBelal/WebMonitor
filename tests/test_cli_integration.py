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
        body = self.server.page_html.encode("utf-8")
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
        self.server.page_html = '<main><div id="watch">initial value</div></main>'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _write_config(self, directory: Path) -> Path:
        config_path = directory / "config.json"
        state_path = directory / "state.json"
        payload = {
            "target_url": f"http://127.0.0.1:{self.server.server_port}/page",
            "css_selector": "#watch",
            "comparison_mode": "text",
            "check_interval_seconds": 1,
            "request_timeout_seconds": 3,
            "state_file": str(state_path),
            "user_agent": "WebMonitor-E2E/1.0",
            "notification": {
                "title": "E2E change",
                "message": "Local fixture changed",
            },
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
            timeout=15,
            check=False,
        )

    def test_cli_baseline_unchanged_change_flow_over_real_http(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            config_path = self._write_config(directory)
            state_path = directory / "state.json"

            baseline = self._run_once(config_path)
            self.assertEqual(baseline.returncode, 0, baseline.stderr)
            self.assertIn("Status: baseline; matched elements: 1", baseline.stdout)
            self.assertNotIn("E2E change", baseline.stdout)

            state_text = state_path.read_text(encoding="utf-8")
            self.assertNotIn("initial value", state_text)
            state_payload = json.loads(state_text)
            self.assertEqual(state_payload["version"], 1)
            self.assertEqual(len(state_payload["monitor_key"]), 64)
            self.assertEqual(len(state_payload["sha256"]), 64)

            unchanged = self._run_once(config_path)
            self.assertEqual(unchanged.returncode, 0, unchanged.stderr)
            self.assertIn("Status: unchanged; matched elements: 1", unchanged.stdout)
            self.assertNotIn("E2E change", unchanged.stdout)

            self.server.page_html = '<main><div id="watch">updated value</div></main>'
            changed = self._run_once(config_path)
            self.assertEqual(changed.returncode, 0, changed.stderr)
            self.assertIn("E2E change: Local fixture changed", changed.stdout)
            self.assertIn("Status: changed; matched elements: 1", changed.stdout)

            updated_state = state_path.read_text(encoding="utf-8")
            self.assertNotIn("updated value", updated_state)

            stable_again = self._run_once(config_path)
            self.assertEqual(stable_again.returncode, 0, stable_again.stderr)
            self.assertIn("Status: unchanged; matched elements: 1", stable_again.stdout)
            self.assertNotIn("E2E change", stable_again.stdout)


if __name__ == "__main__":
    unittest.main()
