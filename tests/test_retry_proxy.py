"""Offline contract checks for the host-side 429 proxy."""
from __future__ import annotations

import http.server
import json
import threading

import httpx

from trace2skill.retry_proxy import RetryProxy, _retry_delay
from skillopt.envs.harbor_pi.security import proxy_credentials


def test_retry_delay():
    assert _retry_delay("0.5", 1) == 0.5
    assert _retry_delay(None, 2) == 10


def test_direct_local_http_is_only_allowed_for_the_explicit_host_retry_proxy(monkeypatch):
    monkeypatch.setenv("TRACE2SKILL_DIRECT_LOCAL", "1")
    monkeypatch.setenv("TRACE2SKILL_TARGET_API_KEY", "dummy-scoped-token")
    monkeypatch.setenv("TRACE2SKILL_TARGET_BASE_URL", "http://host.docker.internal:12345/v1")
    try:
        proxy_credentials("target")
        assert False, "HTTP must be denied without the explicit retry proxy mode"
    except RuntimeError:
        pass
    monkeypatch.setenv("TRACE2SKILL_LOCAL_RETRY_PROXY", "1")
    assert proxy_credentials("target").base_url.endswith(":12345/v1")
    monkeypatch.setenv("TRACE2SKILL_TARGET_BASE_URL", "http://example.org:12345/v1")
    try:
        proxy_credentials("target")
        assert False, "HTTP to a nonlocal host must be denied"
    except RuntimeError:
        pass


def test_proxy_retries_without_changing_request_or_exposing_upstream_key():
    seen = []

    class Upstream(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            seen.append((self.path, body, self.headers["Authorization"]))
            if len(seen) == 1:
                self.send_response(429)
                self.send_header("Retry-After", "0")
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                payload = b'{"ok":true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    proxy = RetryProxy(f"https://127.0.0.1:{server.server_port}/endpoint", "secret-upstream", sleep=lambda _: None)
    # Local fake upstream is deliberately HTTP; only this isolated test rewires transport.
    proxy.upstream_base = f"http://127.0.0.1:{server.server_port}/endpoint"
    proxy.start()
    try:
        body = json.dumps({"model": "fixed", "messages": [{"role": "user", "content": "hello"}]}).encode()
        result = httpx.post(f"http://127.0.0.1:{proxy.server.server_port}/v1/chat/completions",
                            headers={"Authorization": f"Bearer {proxy.downstream_token}"}, content=body)
        assert result.status_code == 200
        assert result.json() == {"ok": True}
        assert seen == [("/endpoint/chat/completions", body, "Bearer secret-upstream")] * 2
        assert proxy.metrics["upstream_429"] == 1
        assert proxy.metrics["retried_requests"] == 1
        assert "secret-upstream" not in json.dumps(proxy.metrics)
    finally:
        proxy.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
