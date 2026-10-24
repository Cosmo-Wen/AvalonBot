import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("openai")

from arena.backends import (BackendError, FatalBackendError, NotLoggedIn, OpenAIBackend,  # noqa: E402
                                TransientBackendError, UsageLimitReached)
from arena.config import load_env_file  # noqa: E402
from arena.retry import is_transient  # noqa: E402

from .conftest import make_cfg  # noqa: E402

FAKE_KEY = "sk-test-0123456789abcdef"

# the stub answers by model name; anything else is a normal reply
ERRORS = {
    "err-401": (401, {"message": f"Incorrect API key provided: {FAKE_KEY}", "type": "invalid_request_error", "code": "invalid_api_key"}),
    "err-401-expired": (401, {"message": "API key expired", "type": "invalid_request_error", "code": None}),
    "err-404": (404, {"message": "model not found", "type": "invalid_request_error", "code": "model_not_found"}),
    "err-429": (429, {"message": "Rate limit reached", "type": "requests", "code": "rate_limit_exceeded"}),
    "err-429-quota": (429, {"message": "You exceeded your current quota", "type": "insufficient_quota", "code": "insufficient_quota"}),
    "err-500": (500, {"message": "server error", "type": "server_error", "code": None}),
}


def response_payload(model, text):
    return {
        "id": "resp_stub", "object": "response", "created_at": 0, "model": model, "status": "completed",
        "output": [{"type": "message", "id": "msg_stub", "status": "completed", "role": "assistant",
                    "content": [{"type": "output_text", "text": text, "annotations": []}]}],
        "usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15,
                  "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}},
        "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
    }


class StubResponsesAPI(BaseHTTPRequestHandler):
    requests = []
    reply = staticmethod(lambda body: "Answer: Yes")

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        StubResponsesAPI.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        if body["model"] in ERRORS:
            status, error = ERRORS[body["model"]]
            payload = {"error": error}
        else:
            status, payload = 200, response_payload(body["model"], StubResponsesAPI.reply(body))
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def api(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubResponsesAPI)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    StubResponsesAPI.requests = []
    monkeypatch.setattr(StubResponsesAPI, "reply", staticmethod(lambda body: "Answer: Yes"))
    monkeypatch.setenv("OPENAI_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    yield StubResponsesAPI.requests
    server.shutdown()


def complete(model="gpt-6.1-sol", effort=None, transcript=None, **cfg):
    b = OpenAIBackend(model, make_cfg(**cfg), effort)
    return asyncio.run(b.complete("You are Player 2.", transcript or [("user", "Vote?")]))


def test_request_shape_and_parsing(api):
    c = complete(transcript=[("user", "intro"), ("agent", "earlier"), ("user", "Vote?")])
    assert (c.text, c.model, c.input_tokens, c.output_tokens) == ("Answer: Yes", "gpt-6.1-sol", 12, 3)
    req = api[0]
    body, headers = req["body"], {k.lower(): v for k, v in req["headers"].items()}
    assert req["path"] == "/v1/responses"
    assert body["store"] is False and body["instructions"] == "You are Player 2."
    assert [m["role"] for m in body["input"]] == ["user", "assistant", "user"]
    assert not {"temperature", "top_p", "reasoning"} & set(body)
    assert headers["authorization"] == f"Bearer {FAKE_KEY}"


def test_effort_maps_to_reasoning(api):
    complete(effort="low")
    assert api[0]["body"]["reasoning"] == {"effort": "low"}


def test_config_base_url_overrides_env(api, monkeypatch):
    url = api and None  # noqa: F841
    base = __import__("os").environ["OPENAI_BASE_URL"]
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9/v1")  # nothing listens here
    complete(openai_base_url=base)
    assert len(api) == 1


@pytest.mark.parametrize("model,exc", [
    ("err-401", NotLoggedIn), ("err-401-expired", UsageLimitReached), ("err-404", FatalBackendError),
    ("err-429", TransientBackendError), ("err-429-quota", UsageLimitReached), ("err-500", BackendError),
])
def test_errors_are_classified(api, model, exc):
    with pytest.raises(exc) as ei:
        complete(model)
    assert type(ei.value) is exc
    assert FAKE_KEY not in str(ei.value)  # key-shaped text from the server is redacted
    assert ei.value.__cause__ is None and ei.value.__suppress_context__
    assert len(api) == 1  # the SDK itself never retries


def test_only_rejected_requests_are_retryable(api):
    # a 5xx or timeout may have been billed, so it must not count as transient
    for model, retryable in [("err-429", True), ("err-500", False)]:
        with pytest.raises(BackendError) as ei:
            complete(model)
        assert is_transient(ei.value) is retryable


def test_timeout_is_not_retried(monkeypatch):
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()  # accepts connections but never answers
    monkeypatch.setenv("OPENAI_BASE_URL", f"http://127.0.0.1:{sock.getsockname()[1]}/v1")
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    try:
        with pytest.raises(BackendError) as ei:
            complete(llm_timeout_s=0.5)
        assert not is_transient(ei.value)
    finally:
        sock.close()


def test_missing_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(NotLoggedIn, match="OPENAI_API_KEY"):
        complete()


def test_env_file_loads_without_overriding(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("# secrets\nOPENAI_API_KEY=sk-from-file-123456\nexport OPENAI_MODEL='gpt-6.1-sol'\nOPENAI_BASE_URL=http://x/v1\n")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://already-set/v1")
    loaded = load_env_file(str(path))
    import os
    assert sorted(loaded) == ["OPENAI_API_KEY", "OPENAI_MODEL"]
    assert os.environ["OPENAI_API_KEY"] == "sk-from-file-123456" and os.environ["OPENAI_MODEL"] == "gpt-6.1-sol"
    assert os.environ["OPENAI_BASE_URL"] == "http://already-set/v1"
    assert load_env_file(str(tmp_path / "missing")) == []
