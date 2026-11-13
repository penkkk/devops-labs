"""Local HTTP contract tests; no root, external network or third-party packages."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import app


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name)
        (self.data / "items.json").write_text('[{"id": 1}]')
        self.log_patch = patch.object(app, "log")
        self.logs = self.log_patch.start()
        self.metrics = app.Metrics()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.make_handler(self.data, "test", self.metrics))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.log_patch.stop()
        self.temp.cleanup()

    def get(self, path, headers=None):
        try:
            response = urlopen(Request(self.base + path, headers=headers or {}), timeout=4)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, response.headers, response.read().decode()

    def test_readiness_is_independent_of_liveness(self):
        self.assertEqual(self.get("/readyz")[0], 200)
        (self.data / "not-ready").touch()
        self.assertEqual(self.get("/readyz")[0], 503)
        self.assertEqual(self.get("/healthz")[0], 200)
        self.assertEqual(self.get("/items")[0], 200)
        (self.data / "not-ready").unlink()
        self.assertEqual(self.get("/readyz")[0], 200)

    def test_corrupt_or_missing_data_produces_503(self):
        (self.data / "items.json").write_text("broken json")
        status, _, body = self.get("/items")
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)["reason"], "data_unavailable")
        (self.data / "items.json").unlink()
        self.assertEqual(self.get("/readyz")[0], 503)
        self.assertEqual(self.get("/healthz")[0], 200)

    def test_request_id_is_preserved_or_replaced(self):
        self.assertEqual(self.get("/", {"X-Request-ID": "lab-123"})[1]["X-Request-ID"], "lab-123")
        request_id = self.get("/", {"X-Request-ID": "invalid/id"})[1]["X-Request-ID"]
        self.assertRegex(request_id, r"^[0-9a-f]{32}$")

    def test_metrics_count_errors_and_bound_unknown_routes(self):
        self.get("/fail")
        self.get("/unknown-123")
        self.get("/unknown-456")
        # The client can finish reading just before the handler records metrics.
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            first = self.get("/metrics")[2]
            if 'ops_demo_http_requests_total{route="other",status="404"} 2' in first:
                break
            time.sleep(0.01)
        self.assertIn('ops_demo_http_requests_total{route="/fail",status="500"} 1', first)
        self.assertIn('ops_demo_http_requests_total{route="other",status="404"} 2', first)
        self.assertIn('ops_demo_http_request_duration_seconds_bucket{route="other",le="+Inf"} 2', first)
        self.assertIn('ops_demo_http_request_duration_seconds_count{route="other"} 2', first)
        self.assertNotIn("unknown-123", first)
        self.assertNotIn("request_id=", first)
        self.assertEqual(self.get("/metrics")[2], first)

    def test_delay_validation_and_failure_status(self):
        self.assertEqual(self.get("/slow?ms=-1")[0], 400)
        self.assertEqual(self.get("/slow?ms=2001")[0], 400)
        self.assertEqual(self.get("/slow?ms=oops")[0], 400)
        self.assertEqual(self.get("/slow?ms=0")[0], 200)
        self.assertEqual(self.get("/fail")[0], 500)

    def test_invalid_port_is_reported_as_json(self):
        result = subprocess.run([sys.executable, str(Path(app.__file__))],
                                env={**os.environ, "APP_PORT": "invalid"},
                                text=True, capture_output=True, timeout=4)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["event"], "startup_failed")


if __name__ == "__main__":
    unittest.main()
