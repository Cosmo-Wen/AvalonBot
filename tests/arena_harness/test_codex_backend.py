import asyncio
import json
import sys

import pytest

from arena.backends import BackendError, NotLoggedIn, UsageLimitReached, make_backend
from arena.codex_backend import CodexCLIBackend
from arena.config import ArenaConfig, load_config
from avalon.arena_play import build_agents
from arena.seeding import deal


def cfg(**kwargs):
    return ArenaConfig(seats=[{"provider": "codex_cli"}] * 5, **kwargs)


def test_events_and_errors():
    backend = CodexCLIBackend("test", cfg(codex_bin="codex"))
    events = [{"type": "item.completed", "item": {"type": "reasoning", "text": "private"}},
              {"type": "item.completed", "item": {"type": "agent_message", "text": "OK"}},
              {"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 3}}]
    result = backend.parse(0, "\n".join(map(json.dumps, events)), "", .1)
    assert (result.text, result.input_tokens, result.output_tokens) == ("OK", 12, 3)
    for text, error in [("usage limit reached", UsageLimitReached), ("authentication required", NotLoggedIn)]:
        with pytest.raises(error):
            backend.parse(1, json.dumps({"type": "turn.failed", "error": {"message": text}}), "", 0)
    with pytest.raises(BackendError):
        backend.parse(0, "garbage", "", 0)


def test_subprocess_tool_adapter(tmp_path, monkeypatch):
    code = f'''import json, os, sys
args = sys.argv
assert os.getcwd() != {str(tmp_path)!r}
assert "OPENAI_API_KEY" not in os.environ
assert "--ignore-user-config" in args and "--ephemeral" in args
prompt = sys.stdin.read()
assert "vote_on_team" in prompt
schema = json.load(open(args[args.index("--output-schema") + 1]))
assert schema["properties"]["name"]["enum"] == ["vote_on_team"]
print(json.dumps({{"type": "item.completed", "item": {{"type": "agent_message", "text": json.dumps({{"name": "vote_on_team", "arguments": '{{"approve": true}}'}})}}}}))
print(json.dumps({{"type": "turn.completed", "usage": {{"input_tokens": 2, "output_tokens": 4}}}}))
'''
    if sys.platform == "win32":
        py_stub = tmp_path / "codex_script.py"
        py_stub.write_text(code)
        stub = tmp_path / "codex.cmd"
        stub.write_text(f'@"{sys.executable}" "{py_stub}" %*\n')
    else:
        stub = tmp_path / "codex"
        stub.write_text(f"#!{sys.executable}\n" + code)
        stub.chmod(0o755)
    monkeypatch.setenv("OPENAI_API_KEY", "unused")
    backend = make_backend(cfg(codex_bin=str(stub)).seats[0], cfg(codex_bin=str(stub)), 0)
    from avalon.tools import get_tool
    result = asyncio.run(backend.chat({"messages": [{"role": "user", "content": "Vote"}],
        "tools": [get_tool("vote_on_team"), get_tool("recall")],
        "tool_choice": {"type": "function", "function": {"name": "vote_on_team"}}}))
    call = result["choices"][0]["message"]["tool_calls"][0]
    assert json.loads(call["function"]["arguments"]) == {"approve": True}
    assert result["usage"]["completion_tokens"] == 4


def test_configs():
    for condition in ("chat_only", "belief_graph", "rule_graph"):
        config = load_config(f"configs/arena/codex_{condition}.yaml")
        assert config.condition == condition
        assert all(s.provider == "codex_cli" for s in config.seats)


def test_game_agents_use_codex_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = cfg(codex_bin="codex")
    agents = build_agents(deal(config, 0), config, None)
    assert all(isinstance(a.transport, CodexCLIBackend) for a in agents.values())
