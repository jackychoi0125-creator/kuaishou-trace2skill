"""Host-side OpenAI-compatible pass-through with bounded HTTP 429 backoff.

The fixed Pi/Harbor target sends its unchanged JSON request to this proxy.
Only the Authorization header is replaced with the upstream credential. The
upstream response is streamed back unchanged on success. No request or model
response body is persisted by this module.
"""
from __future__ import annotations

import email.utils
import hmac
import http.server
import json
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx


def _retry_delay(header: str | None, attempt: int) -> float:
    if header:
        try:
            return min(90.0, max(0.0, float(header)))
        except ValueError:
            try:
                date = email.utils.parsedate_to_datetime(header)
                return min(90.0, max(0.0, (date - datetime.now(timezone.utc)).total_seconds()))
            except (TypeError, ValueError, OverflowError):
                pass
    return min(60.0, 5.0 * (2 ** (attempt - 1)))


class RetryProxy:
    def __init__(self, upstream_base: str, upstream_key: str, *, port: int = 0,
                 max_attempts: int = 6, sleep=time.sleep):
        parsed = urlsplit(upstream_base.rstrip("/"))
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("upstream base must be an absolute HTTPS URL without query or fragment")
        if not upstream_key or max_attempts < 1:
            raise ValueError("upstream credential and positive retry count are required")
        self.upstream_base = upstream_base.rstrip("/")
        self.upstream_key = upstream_key
        self.downstream_token = secrets.token_urlsafe(24)
        self.max_attempts = max_attempts
        self.sleep = sleep
        self.metrics = {"requests": 0, "upstream_429": 0, "retried_requests": 0,
                        "retry_exhausted": 0, "other_upstream_errors": 0, "wait_seconds": 0.0}
        self._lock = threading.Lock()
        # An upstream stream that stops sending bytes must not hold a Harbor
        # trial forever. This is an idle-read timeout, not a completion cap.
        self._client = httpx.Client(timeout=httpx.Timeout(connect=30.0, read=300.0, write=60.0, pool=30.0),
                                    trust_env=False, follow_redirects=False)
        proxy = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format, *_args):
                # Never log URL, headers, request body, or response body.
                return

            def do_GET(self):
                if self.path == "/health":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", "11")
                    self.end_headers()
                    self.wfile.write(b'{"ok":true}')
                    return
                self.send_error(404)

            def do_POST(self):
                self.close_connection = True
                if not self.path.startswith("/v1/") or "?" in self.path:
                    self.send_error(404)
                    return
                supplied = self.headers.get("Authorization", "")
                if not hmac.compare_digest(supplied, f"Bearer {proxy.downstream_token}"):
                    self.send_error(401)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "-1"))
                except ValueError:
                    length = -1
                if length < 0 or length > 32_000_000:
                    self.send_error(413)
                    return
                body = self.rfile.read(length)
                url = proxy.upstream_base + self.path[len("/v1"):]
                headers = {k: v for k, v in self.headers.items()
                           if k.lower() not in {"authorization", "host", "connection", "content-length",
                                                "transfer-encoding", "accept-encoding", "x-api-key"}}
                headers["Authorization"] = f"Bearer {proxy.upstream_key}"
                headers["Accept-Encoding"] = "identity"
                with proxy._lock:
                    proxy.metrics["requests"] += 1
                for attempt in range(1, proxy.max_attempts + 1):
                    try:
                        with proxy._client.stream("POST", url, content=body, headers=headers) as response:
                            if response.status_code == 429 and attempt < proxy.max_attempts:
                                with proxy._lock:
                                    proxy.metrics["upstream_429"] += 1
                                    if attempt == 1:
                                        proxy.metrics["retried_requests"] += 1
                                delay = _retry_delay(response.headers.get("Retry-After"), attempt)
                                with proxy._lock:
                                    proxy.metrics["wait_seconds"] += delay
                                proxy.sleep(delay)
                                continue
                            if response.status_code == 429:
                                with proxy._lock:
                                    proxy.metrics["upstream_429"] += 1
                                    proxy.metrics["retry_exhausted"] += 1
                            elif response.status_code >= 400:
                                with proxy._lock:
                                    proxy.metrics["other_upstream_errors"] += 1
                            self.send_response(response.status_code)
                            for key, value in response.headers.items():
                                if key.lower() not in {"connection", "transfer-encoding", "content-length",
                                                       "keep-alive", "content-encoding"}:
                                    self.send_header(key, value)
                            self.send_header("Connection", "close")
                            self.end_headers()
                            for chunk in response.iter_bytes():
                                if chunk:
                                    self.wfile.write(chunk)
                                    self.wfile.flush()
                            return
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        # The Pi client may stop reading after its trial exits. This is
                        # a downstream disconnect, not an upstream model failure.
                        return
                    except (httpx.HTTPError, OSError):
                        with proxy._lock:
                            proxy.metrics["other_upstream_errors"] += 1
                        try:
                            self.send_error(502, "upstream transport error")
                        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                            pass
                        return

        self.server = http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler)
        self.thread: threading.Thread | None = None

    @property
    def container_base_url(self) -> str:
        return f"http://host.docker.internal:{self.server.server_port}/v1"

    def start(self) -> None:
        if self.thread is not None:
            raise RuntimeError("proxy already started")
        self.thread = threading.Thread(target=self.server.serve_forever, name="trace2skill-retry-proxy", daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._client.close()
        if self.thread is not None:
            self.thread.join(timeout=5)

    def write_metrics(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            public = dict(self.metrics)
        public.update({"max_attempts": self.max_attempts, "upstream_credential_persisted": False,
                       "request_or_response_bodies_persisted": False})
        path.write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
