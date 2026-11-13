#!/usr/bin/env python3
"""Isolated lab HTTP server: structured logs, readiness and bounded fault routes."""

import json
import math
import os
import re
import sys
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, math.inf)
ROUTES = {"/", "/healthz", "/readyz", "/items", "/fail", "/slow"}


def log(**fields):
    print(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), **fields}), flush=True)


class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.requests = defaultdict(int)
        self.durations = {}

    def observe(self, route, status, elapsed):
        with self.lock:
            self.requests[(route, status)] += 1
            row = self.durations.setdefault(route, {"buckets": [0] * len(BUCKETS), "sum": 0, "count": 0})
            row["sum"] += elapsed
            row["count"] += 1
            for index, upper in enumerate(BUCKETS):
                if elapsed <= upper:
                    row["buckets"][index] += 1

    def render(self):
        with self.lock:
            lines = [
                "# HELP ops_demo_http_requests_total Completed non-scrape GET requests.",
                "# TYPE ops_demo_http_requests_total counter",
            ]
            for (route, status), count in sorted(self.requests.items()):
                lines.append(f'ops_demo_http_requests_total{{route="{route}",status="{status}"}} {count}')
            prefix = "ops_demo_http_request_duration_seconds"
            lines += [f"# HELP {prefix} Non-scrape GET duration in seconds.", f"# TYPE {prefix} histogram"]
            for route, row in sorted(self.durations.items()):
                for upper, count in zip(BUCKETS, row["buckets"]):
                    label = "+Inf" if math.isinf(upper) else str(upper)
                    lines.append(f'{prefix}_bucket{{route="{route}",le="{label}"}} {count}')
                lines.append(f'{prefix}_sum{{route="{route}"}} {row["sum"]:.9f}')
                lines.append(f'{prefix}_count{{route="{route}"}} {row["count"]}')
            return "\n".join(lines) + "\n"


def make_handler(data_dir, version, metrics):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            started = time.monotonic()
            parsed = urlsplit(self.path)
            path = parsed.path
            request_id = self.headers.get("X-Request-ID", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request_id):
                request_id = uuid.uuid4().hex
            status, payload, error = 200, {"ok": True, "version": version}, None
            if path == "/metrics":
                body = metrics.render().encode()
                content_type = "text/plain; version=0.0.4; charset=utf-8"
            else:
                if path in ("/readyz", "/items"):
                    try:
                        if path == "/readyz" and (data_dir / "not-ready").exists():
                            raise RuntimeError("readiness disabled")
                        items = json.loads((data_dir / "items.json").read_text())
                        if not isinstance(items, list):
                            raise ValueError("items must be a list")
                        if path == "/items":
                            payload = items
                    except (OSError, ValueError, RuntimeError) as exc:
                        status, payload, error = 503, {"ok": False, "reason": "data_unavailable"}, type(exc).__name__
                elif path == "/fail":
                    status, payload = 500, {"ok": False, "reason": "intentional_failure"}
                elif path == "/slow":
                    try:
                        ms = int(parse_qs(parsed.query).get("ms", ["700"])[0])
                        if not 0 <= ms <= 2000:
                            raise ValueError("delay out of range")
                        time.sleep(ms / 1000)
                    except ValueError:
                        status, payload = 400, {"ok": False, "reason": "ms_must_be_0_to_2000"}
                elif path not in ROUTES:
                    status, payload = 404, {"ok": False, "reason": "not_found"}
                body = json.dumps(payload).encode()
                content_type = "application/json"
            disconnected = False
            try:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Request-ID", request_id)
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                disconnected = True
            if path != "/metrics":
                elapsed = time.monotonic() - started
                metrics.observe(path if path in ROUTES else "other", status, elapsed)
                fields = dict(level="ERROR" if status >= 500 else "INFO", event="http_request",
                              request_id=request_id, method="GET", path=path, status=status,
                              duration_ms=round(elapsed * 1000, 3), version=version)
                if error:
                    fields["error"] = error
                if disconnected:
                    fields["client_disconnected"] = True
                log(**fields)

    return Handler


def main():
    try:
        port = int(os.environ.get("APP_PORT", "8080"))
        if not 1 <= port <= 65535:
            raise ValueError("APP_PORT must be 1..65535")
        host = os.environ.get("APP_HOST", "127.0.0.1")
        version = os.environ.get("APP_VERSION", "dev")
        data_dir = Path(os.environ.get("DATA_DIR", str(Path(__file__).parent / "data")))
        server = ThreadingHTTPServer((host, port), make_handler(data_dir, version, Metrics()))
    except (OSError, ValueError) as exc:
        log(level="ERROR", event="startup_failed", error=str(exc))
        return 1
    log(level="INFO", event="started", host=host, port=port, version=version, data_dir=str(data_dir))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
