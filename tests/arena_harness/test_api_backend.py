import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("anthropic")

from arena.backends import (AnthropicBackend, BackendError, FatalBackendError, ModelRefusal,  # noqa: E402
                                NotLoggedIn, TransientBackendError, UsageLimitReached)
from arena.runner import _classify  # noqa: E402

from .conftest import make_cfg  # noqa: E402

# the stub API answers by model name; anything else is a normal reply
ERRORS = {
    "err-401": (401, "authentication_error"), "err-402": (402, "billing_error"),
    "err-404": (404, "not_found_error"), "err-429": (429, "rate_limit_error"),
    "err-529": (529, "overloaded_error"), "err-400": (400, "invalid_request_error"),
}


class StubAPI(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        StubAPI.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        model = body["model"]
        if model in ERRORS:
            status, kind = ERRORS[model]
            payload = {"type": "error", "error": {"type": kind, "message": f"stub {kind}"}}
        else:
            status = 200
            refusal = model == "claude-refuses"
            payload = {
                "id": "msg_stub", "type": "message", "role": "assistant", "model": model,
                "content": [] if refusal else [{"type": "thinking", "thinking": "", "signature": "sig"},
                                               {"type": "text", "text": "Answer: Yes"}],
                "stop_reason": "refusal" if refusal else "end_turn", "stop_sequence": None,
                "stop_details": {"type": "refusal", "category": "cyber", "explanation": None} if refusal else None,
                "usage": {"input_tokens": 10, "output_tokens": 4, "cache_creation_input_tokens": 1000,
                          "cache_read_input_tokens": 2000},
            }
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def api(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubAPI)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    StubAPI.requests = []
    monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    yield StubAPI.requests
    server.shutdown()


def complete(model, effort="medium", transcript=None):
    b = AnthropicBackend(model, make_cfg(), effort)
    return asyncio.run(b.complete("You are Player 2.", transcript or [("user", "Vote?")]))


def test_request_shape_and_parsing(api):
    c = complete("opus", transcript=[("agent", "earlier reply"), ("user", "Vote?")])
    assert c.text == "Answer: Yes" and c.model == "claude-opus-5-5"
    assert (c.input_tokens, c.output_tokens) == (3010, 4)
    assert c.cost_usd == pytest.approx((10 * 4 + 1000 * 5 + 2000 * 0.4 + 4 * 20) / 1e6)
    req = api[0]
    body, headers = req["body"], {k.lower(): v for k, v in req["headers"].items()}
    assert req["path"].startswith("/v1/messages")
    assert body["model"] == "claude-opus-5-5" and body["system"] == "You are Player 2."
    assert body["output_config"] == {"effort": "medium"} and body["cache_control"] == {"type": "ephemeral"}
    assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in headers["anthropic-beta"]
    assert not {"temperature", "top_p", "top_k", "thinking"} & set(body)
    # history starting on our own reply gets a user turn first; last turn is the user's (no prefill)
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"]
    # SDK 2.x sends the key as a bearer token and defaults to API version 2026-10-21
    assert headers["authorization"] == "Bearer sk-ant-test"
    assert headers["anthropic-version"] == "2026-10-21"


def test_haiku_gets_no_fallback_and_effort_can_be_omitted(api):
    complete("haiku", effort=None)
    body = api[0]["body"]
    assert body["model"] == "claude-haiku-5-5"
    assert "fallbacks" not in body and "output_config" not in body


def test_refusal_is_a_terminal_model_outcome(api):
    with pytest.raises(ModelRefusal, match="cyber") as ei:
        complete("claude-refuses")
    assert _classify(ei.value) == "refusal"


@pytest.mark.parametrize("model,exc", [
    ("err-401", NotLoggedIn), ("err-402", UsageLimitReached), ("err-404", FatalBackendError),
    ("err-429", TransientBackendError), ("err-529", TransientBackendError), ("err-400", BackendError),
])
def test_errors_are_classified(api, model, exc):
    with pytest.raises(exc) as ei:
        complete(model)
    assert type(ei.value) is exc or model == "err-400"
    assert len(api) == 1  # the SDK itself does not retry; the arena owns retries


def test_missing_credentials_is_fatal(monkeypatch, api):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", "/nonexistent-arena-test")  # no `ant auth login` profile
    with pytest.raises(FatalBackendError):
        complete("opus")
