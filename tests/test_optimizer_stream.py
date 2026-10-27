from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from skillopt.model import openai_compatible_backend as backend


class FakeStream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    def __iter__(self):
        return iter(self.chunks)

    def close(self):
        self.closed = True


def test_optimizer_stream_preserves_usage_and_request_controls(monkeypatch, tmp_path):
    calls = []
    stream = FakeStream([
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None, reasoning_content="hidden"), finish_reason=None)], usage=None),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='{"edits":[],"debug":"dummy-test-secret"}'), finish_reason="stop")], usage=None),
        SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=40, completion_tokens=30,
                                                         completion_tokens_details=SimpleNamespace(reasoning_tokens=20),
                                                         prompt_tokens_details=SimpleNamespace(cached_tokens=10))),
    ])

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return stream

    monkeypatch.setattr(backend, "_get_client", lambda role: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())))
    monkeypatch.setattr(backend, "OPTIMIZER_CONFIG", replace(
        backend.OPTIMIZER_CONFIG, stream=True, max_tokens=90000, api_key="dummy-test-secret",
        completion_token_field="max_completion_tokens", thinking="enabled", reasoning_effort="high",
    ))
    monkeypatch.setenv("TRACE2SKILL_OPTIMIZER_RESPONSE_DIR", str(tmp_path / "responses"))
    backend.set_optimizer_token_budget(None)
    backend.reset_token_tracker()
    result, usage = backend.chat_optimizer("system", "user", retries=1, stage="analyst")
    assert result == '{"edits":[],"debug":"dummy-test-secret"}'
    assert calls[0]["stream"] is True
    assert calls[0]["stream_options"] == {"include_usage": True}
    assert calls[0]["max_completion_tokens"] == 90000
    assert calls[0]["extra_body"]["thinking"] == {"type": "enabled"}
    assert stream.closed
    assert usage["reasoning_content_present"] is True
    assert usage["finish_reason"] == "stop"
    totals = backend.get_token_summary()["_total"]
    assert totals["prompt_tokens"] == 40
    assert totals["completion_tokens"] == 30
    assert totals["reasoning_tokens"] == 20
    assert totals["cached_tokens"] == 10
    assert totals["total_tokens"] == 70
    saved = list((tmp_path / "responses").glob("*.json"))
    assert len(saved) == 1
    assert "dummy-test-secret" not in saved[0].read_text()
    assert saved[0].stat().st_mode & 0o077 == 0


def test_optimizer_stream_fails_closed_without_server_usage(monkeypatch):
    stream = FakeStream([SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="x", reasoning_content=None), finish_reason="stop")], usage=None)])
    monkeypatch.setattr(backend, "_get_client", lambda role: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: stream))))
    monkeypatch.setattr(backend, "OPTIMIZER_CONFIG", replace(backend.OPTIMIZER_CONFIG, stream=True))
    backend.set_optimizer_token_budget(None)
    with pytest.raises(RuntimeError, match="without server token usage"):
        backend.chat_optimizer("system", "user", retries=1, stage="analyst")
    assert stream.closed
