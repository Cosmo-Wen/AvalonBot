import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from arena.events import EventLog, read_events
from avalon.arena_play import LoggedLLMAgent, is_gateway_rejection
from avalon.engine import Role

REJECTION = {"error": {"code": "gateway_concurrency_limit",
                       "message": "Concurrency limit exceeded for user, please retry later", "type": "rate_limit_error"}}


class StubGateway(BaseHTTPRequestHandler):
    limit = 3
    lock = threading.Lock()
    inflight = 0
    peak = 0
    rejected = 0
    served = 0

    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers["content-length"]))
        cls = StubGateway
        with cls.lock:
            cls.inflight += 1
            cls.peak = max(cls.peak, cls.inflight)
            over = cls.inflight > cls.limit
        try:
            if over:
                with cls.lock:
                    cls.rejected += 1
                status, payload = 429, REJECTION
            else:
                time.sleep(0.05)
                with cls.lock:
                    cls.served += 1
                status, payload = 200, {"model": "stub", "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                                        "choices": [{"message": {"role": "assistant", "content": "ok"}}]}
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        finally:
            with cls.lock:
                cls.inflight -= 1


@pytest.fixture
def gateway():
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubGateway)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    StubGateway.inflight = StubGateway.peak = StubGateway.rejected = StubGateway.served = 0
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()


def agents(url, log, n, max_inflight):
    return [LoggedLLMAgent(player_id=i % 5, role=Role.LOYAL_SERVANT, condition="chat_only", api_key="test",
                           base_url=url, model="stub", log=log, max_inflight=max_inflight,
                           max_retries=8, backoff_base_s=0.01, backoff_max_s=0.05) for i in range(n)]


def burst(url, tmp_path, max_inflight, n=12):
    log = EventLog(str(tmp_path / "g.jsonl"), run_id="t", game_idx=0)
    team = agents(url, log, n, max_inflight)

    async def main():
        return await asyncio.gather(*(a._post({"model": "stub", "messages": [{"role": "user", "content": "hi"}]})
                                      for a in team))

    results = asyncio.run(main())
    log.close()
    return team, results, read_events(str(tmp_path / "g.jsonl"))


def test_cap_keeps_requests_under_the_gateway_limit(gateway, tmp_path):
    team, results, events = burst(gateway, tmp_path, max_inflight=3)
    assert len(results) == 12 and StubGateway.peak <= 3 and StubGateway.rejected == 0
    assert sum(a.calls for a in team) == 12 and not any(e["type"] == "retry" for e in events)


def test_gateway_rejections_are_retried_not_played_as_fallbacks(gateway, tmp_path):
    team, results, events = burst(gateway, tmp_path, max_inflight=12)
    assert StubGateway.rejected > 0  # the cap was above the gateway's limit
    assert len(results) == 12 and all(r["choices"][0]["message"]["content"] == "ok" for r in results)
    retries = [e for e in events if e["type"] == "retry"]
    assert len(retries) == StubGateway.rejected == sum(a.retries for a in team)
    assert sum(a.errors for a in team) == 0 and all(a.fatal is None for a in team)


def test_rejection_classification():
    assert is_gateway_rejection("LLM API Error (429): " + json.dumps(REJECTION))
    assert not is_gateway_rejection('LLM API Error (429): {"error": {"code": "insufficient_quota", "type": "rate_limit_error"}}')
    assert not is_gateway_rejection("LLM API Error (500): oops")
