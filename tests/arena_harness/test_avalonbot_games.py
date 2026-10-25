import asyncio
import json
from collections import Counter

import pytest

from arena.config import ArenaConfig
from arena.events import read_events
from arena.runner import game_path, run
from arena.__main__ import summarize
from avalon.arena_adapter import ArenaGraphAdapter
from avalon.arena_play import classify_http_error
from arena.backends import FatalBackendError, NotLoggedIn, UsageLimitReached


def heuristic_cfg(condition, **overrides):
    base = dict(seats=[{"provider": "fake", "name": f"h{i}"} for i in range(5)], num_games=3,
                base_seed=0, concurrency=3, condition=condition)
    base.update(overrides)
    return ArenaConfig.model_validate(base)


@pytest.mark.parametrize("condition", ["chat_only", "belief_graph", "rule_graph"])
def test_avalonbot_games_run_through_the_arena(tmp_path, condition):
    run_dir = str(tmp_path / condition)
    ends = asyncio.run(run(heuristic_cfg(condition), run_dir, log_fn=lambda *_: None))
    assert [e["data"]["status"] for e in ends] == ["completed"] * 3
    assert summarize(run_dir)["statuses"] == {"completed": 3}
    for i in range(3):
        events = read_events(game_path(run_dir, i))
        start = events[0]["data"]
        assert start["condition"] == condition
        # evil always plays chat-only; the good team plays the configured condition
        for seat in start["seats"]:
            evil = seat["role"] in ("Assassin", "Minion")
            assert seat["condition"] == ("chat_only" if evil else condition)


def test_discussion_happens_once_per_quest(tmp_path):
    # seed chosen so some quests take more than one proposal
    run_dir = str(tmp_path / "run")
    asyncio.run(run(heuristic_cfg("rule_graph", num_games=6), run_dir, log_fn=lambda *_: None))
    saw_repeat_proposal = False
    for i in range(6):
        events = read_events(game_path(run_dir, i))
        rounds = {(e["data"]["quest"], e["data"]["round"]) for e in events if e["type"] == "discussion"}
        assert all(r == 0 for _, r in rounds)
        assert Counter(q for q, _ in rounds) == Counter({q: 1 for q, _ in rounds})
        speeches = Counter(e["data"]["quest"] for e in events if e["type"] == "discussion")
        assert set(speeches.values()) == {5}
        proposals = Counter(e["data"]["quest"] for e in events if e["type"] == "team_proposed")
        saw_repeat_proposal |= any(n > 1 for n in proposals.values())
    assert saw_repeat_proposal, "pick a seed where some quest needs a second proposal"


def test_adapter_rebuilds_the_in_game_beliefs_from_the_log(tmp_path):
    r"""Arena events -> belief graph: the adapter, fed only the log, reaches the same rule-based P(evil)
    as each Servant's own memory did during the game (condition C beliefs ignore talk edges)."""
    run_dir = str(tmp_path / "run")
    asyncio.run(run(heuristic_cfg("rule_graph", num_games=4), run_dir, log_fn=lambda *_: None))
    for i in range(4):
        events = read_events(game_path(run_dir, i))
        adapter = ArenaGraphAdapter(merlin_graph=False)
        for event in events:
            adapter.feed(event)
        assert adapter.state.violations == []
        beliefs = next(e["data"] for e in events if e["type"] == "beliefs")
        for seat, row in enumerate(beliefs["believed"]):
            if row is None:
                continue
            in_game = {q: 1.0 - v for q, v in enumerate(row) if q != seat}
            rebuilt = adapter.memories[seat].beliefs.p_evil
            assert rebuilt == pytest.approx(in_game)
        assert adapter.state.good_won == (events[-1]["data"]["winner"] == "good")


def test_http_errors_that_stop_the_run():
    assert isinstance(classify_http_error("LLM API Error (401): bad key"), NotLoggedIn)
    assert isinstance(classify_http_error("LLM API Error (401): key expired"), UsageLimitReached)
    assert isinstance(classify_http_error("LLM API Error (429): quota exceeded"), UsageLimitReached)
    assert isinstance(classify_http_error("LLM API Error (402): payment"), UsageLimitReached)
    assert isinstance(classify_http_error("LLM API Error (404): no model"), FatalBackendError)
    assert classify_http_error("LLM API Error (500): oops") is None


def test_llm_seats_need_a_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = heuristic_cfg("chat_only", seats=[{"provider": "openai", "model": "gpt-6.1-sol"}] * 5, num_games=1)
    with pytest.raises(NotLoggedIn):
        asyncio.run(run(cfg, str(tmp_path / "run"), log_fn=lambda *_: None))
