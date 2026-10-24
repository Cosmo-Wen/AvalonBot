import asyncio
import json

from arena.backends import Completion
from avalon.arena_play import LoggedCLIAgent, _parse_tool_reply, _render_conversation
from avalon.engine import Role
from avalon.tools import get_tool
from arena.events import EventLog, read_events


class StubCLI:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    async def complete(self, system, transcript):
        self.prompts.append((system, transcript[0][1]))
        return Completion(text=self.replies.pop(0), input_tokens=10, output_tokens=3, cost_usd=0.001,
                          model="claude-haiku", duration_s=0.1)


def agent(tmp_path, replies):
    log = EventLog(str(tmp_path / "g.jsonl"), run_id="t", game_idx=0)
    cli = StubCLI(replies)
    a = LoggedCLIAgent(player_id=0, role=Role.LOYAL_SERVANT, condition="chat_only", model="haiku",
                       api_key="claude-cli", cli=cli, log=log, max_inflight=2)
    return a, cli, log


def test_parse_tool_reply_skips_prose_and_fences():
    assert _parse_tool_reply('```json\n{"tool": "vote_on_team", "arguments": {"approve": true}}\n```',
                             ["vote_on_team"]) == {"tool": "vote_on_team", "arguments": {"approve": True}}
    assert _parse_tool_reply('I approve. {"note": 1} then {"tool": "vote_on_team", "arguments": {}}',
                             ["vote_on_team"])["tool"] == "vote_on_team"
    assert _parse_tool_reply('{"tool": "other", "arguments": {}}', ["vote_on_team"]) is None


def test_render_conversation_keeps_tool_rounds():
    text = _render_conversation([
        {"role": "system", "content": "sys"}, {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "function": {"name": "recall", "arguments": '{"q": 1}'}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "result"}])
    assert "sys" not in text and "[Game]\nhi" in text and '"tool": "recall"' in text and "[Tool result]\nresult" in text


def test_forced_tool_call_round_trips_and_is_logged(tmp_path):
    a, cli, log = agent(tmp_path, ['{"tool": "vote_on_team", "arguments": {"approve": false}}'])
    tool = get_tool("vote_on_team")
    data = asyncio.run(a._post({"model": "haiku", "messages": [{"role": "system", "content": "sys"},
                                                               {"role": "user", "content": "vote"}],
                                "tools": [tool], "tool_choice": {"type": "function", "function": {"name": "vote_on_team"}}}))
    log.close()
    call = data["choices"][0]["message"]["tool_calls"][0]
    assert call["function"]["name"] == "vote_on_team" and json.loads(call["function"]["arguments"]) == {"approve": False}
    assert cli.prompts[0][0] == "sys" and 'Use the tool "vote_on_team"' in cli.prompts[0][1]
    logged = [e["data"] for e in read_events(str(tmp_path / "g.jsonl")) if e["type"] == "llm_call"]
    assert logged[0]["cost_usd"] == 0.001 and logged[0]["tool_calls"][0]["name"] == "vote_on_team"


def test_plain_text_call_has_no_tool_instructions(tmp_path):
    a, cli, log = agent(tmp_path, ["I think P3 is fine."])
    data = asyncio.run(a._post({"model": "haiku", "messages": [{"role": "system", "content": "sys"},
                                                               {"role": "user", "content": "speak"}]}))
    log.close()
    assert data["choices"][0]["message"]["content"] == "I think P3 is fine." and "Tools:" not in cli.prompts[0][1]
