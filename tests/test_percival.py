import asyncio
import math
from dataclasses import replace

import pytest

from arena.config import load_config
from arena.events import read_events
from arena.runner import run, game_path
from arena.seeding import deal
from arena.__main__ import summarize
from avalon.agents import HeuristicAgent
from avalon.arena_adapter import ArenaGraphAdapter
from avalon.engine import AvalonEngine, Role
from avalon.llm_agent import LLMAgent
from avalon.memory import LogEntry, PlayerMemory
from avalon.percival import PercivalBelief
from avalon.percival_metrics import summarize_percival, vote_accuracy_metrics

ROLES = {0: Role.PERCIVAL, 1: Role.MERLIN, 2: Role.MORGANA, 3: Role.ASSASSIN, 4: Role.LOYAL_SERVANT}


def entry(kind, seq=1, **kw):
    return LogEntry(seq, kind, 1, 1, **kw)


def test_reveals_and_old_role_ids():
    e = AvalonEngine()
    e.reset(ROLES)
    assert [int(Role.MERLIN), int(Role.LOYAL_SERVANT), int(Role.MINION), int(Role.ASSASSIN)] == [0, 1, 2, 3]
    for p in ROLES:
        info = e.get_private_info(p)
        assert info['seen_evil'] == {0: [], 1: [2, 3], 2: [3], 3: [2], 4: []}[p]
        assert info.get('merlin_candidates') == ([1, 2] if p == 0 else None)
    assert e.QUEST_SIZES == [2, 3, 2, 3, 3]
    assert e.FAILS_REQUIRED == [1] * 5
    assert len(PlayerMemory(4, e.get_private_info(4)).beliefs.all_pairs) == 6
    with pytest.raises(ValueError):
        e.reset({**ROLES, 4: Role.MERLIN})


@pytest.mark.parametrize('event,factors', [
    (entry('proposal', leader=1, members=(0, 2)), [.1, .1, 1, 1]),
    (entry('proposal', leader=1, members=(0, 3)), [.2, 1, 1, 1]),
    (entry('team_vote', members=(0, 3), votes=((1, True), (2, False))), [.1, 1, 1, 1]),
    (entry('team_vote', members=(0, 3), votes=((1, False), (2, False))), [.5, 1, .5, 1]),
    (entry('team_vote', members=(0, 3), votes=((1, False), (2, True))), [1, 1, .1, 1]),
    (entry('quest_result', members=(0, 1), success=True, fails=0), [1, 1, 1, 1]),
])
def test_factors(event, factors):
    b = PercivalBelief(0, [1, 2])
    b.update(event)
    assert b.weights == pytest.approx([f / sum(factors) for f in factors])
    assert sum(b.p_evil.values()) == pytest.approx(2)
    assert sum(b.p_merlin.values()) == pytest.approx(1)
    assert b.p_evil[1] == pytest.approx(1 - b.p_merlin[1])


def test_hard_evidence_atomicity_and_duplicate_guard():
    b = PercivalBelief(0, [1, 2])
    b.update(entry('quest_result', members=(0, 1), success=False, fails=1))
    assert b.weights == [0, 0, .5, .5]
    assert b.p_merlin == {1: 0, 2: 1}
    before = b.snapshot()
    with pytest.raises(ValueError, match='contradicts'):
        b.update(entry('quest_result', seq=2, members=(0, 2), success=False, fails=1))
    assert b.snapshot() == before
    with pytest.raises(ValueError, match='Duplicate'):
        b.update(entry('utterance'))
    double = PercivalBelief(0, [1, 2])
    double.update(entry('quest_result', members=(1, 3), success=False, fails=2))
    assert double.weights == [0, 0, 1, 0]


def test_stability_and_forced_votes():
    b = PercivalBelief(0, [1, 2])
    b.update(replace(entry('team_vote', members=(0, 2), votes=((1, True),)), attempt=5))
    assert b.weights == [.25] * 4
    for seq in range(2, 1200):
        b.update(entry('proposal', seq, leader=1, members=(0, 2)))
    assert all(w > 0 for w in b.weights)
    assert all(math.isfinite(w) for w in b.weights)
    assert b.following() == 2


def make_agent(cls=LLMAgent, **kwargs):
    e = AvalonEngine()
    e.reset(ROLES)
    a = cls(0, Role.PERCIVAL, percival_condition='four_world', **kwargs)
    a.set_private_info(e.get_private_info(0))
    return a


@pytest.mark.parametrize('probability,expected', [(0.55, False), (.550001, True), (.5, False)])
def test_vote_cutoff_including_self(probability, expected, monkeypatch):
    a = make_agent()
    monkeypatch.setattr(a.memory.percival, 'all_good', lambda team: probability)
    assert asyncio.run(a.vote_on_team(0, 0, 1, [0, 1])) is expected
    assert asyncio.run(a.vote_on_team(0, 4, 1, [0, 1])) is True
    h = make_agent(HeuristicAgent)
    monkeypatch.setattr(h.memory.percival, 'all_good', lambda team: probability)
    assert h._decide_team_vote(0, [0, 1])[0] is expected


def test_following_boundary_and_prompts():
    a = make_agent()
    a.memory.percival.log_weights = [math.log(v) for v in [.4, .4, .1, .1]]
    assert a.memory.percival.following() is None
    a.memory.percival.log_weights = [math.log(v) for v in [.41, .4, .1, .09]]
    assert a.memory.percival.following() == 1
    assert 'Privately follow Player 1' in a._memory_context()
    assert 'Never name Merlin' in a._build_system_prompt()
    assert 'Percival' in a._build_system_prompt()


class Transport:
    def __init__(self):
        self.calls = []

    async def chat(self, payload):
        self.calls.append(payload)
        choice = payload.get('tool_choice')
        name = choice['function']['name'] if isinstance(choice, dict) else None
        args = {'team': [0, 1]} if name == 'propose_team' else {'p_evil': {'0': .5, '1': .5, '2': .5, '3': .5}}
        message = {'content': 'Public evidence supports this team.'}
        if name:
            import json
            message['tool_calls'] = [{'function': {'name': name, 'arguments': json.dumps(args)}}]
        return {'choices': [{'message': message}]}


def test_real_agent_methods_call_transport_without_key(monkeypatch):
    for key in ['OPENAI_API_KEY', 'BOSON_API_KEY']:
        monkeypatch.delenv(key, raising=False)
    transport = Transport()
    e = AvalonEngine()
    e.reset(ROLES)
    a = LLMAgent(4, Role.LOYAL_SERVANT, condition='chat_only', transport=transport)
    a.set_private_info(e.get_private_info(4))
    async def exercise():
        assert await a.team_discussion(0, 0, 0, 2) == 'Public evidence supports this team.'
        assert await a.propose_team(0, 2) == [0, 1]
        await a.after_discussion(0, 0)
        await a.final_beliefs()
    asyncio.run(exercise())
    assert len(transport.calls) == 4


@pytest.mark.parametrize('label', ['p0', 'p1'])
def test_offline_games_replay_and_metrics(tmp_path, label):
    config = load_config(f'configs/arena/percival_{label}.yaml')
    config.num_games = 3
    for seat in config.seats:
        seat.provider = 'fake'
    result = asyncio.run(run(config, str(tmp_path), log_fn=lambda *_: None))
    assert all(r['data']['status'] == 'completed' for r in result)
    for i in range(3):
        adapter = ArenaGraphAdapter(merlin_graph=False)
        for event in read_events(game_path(str(tmp_path), i)):
            adapter.feed(event)
            if event['type'] == 'percival_beliefs':
                expected = adapter.memories[event['data']['seat']].percival.snapshot()
                assert [w['weight'] for w in expected['worlds']] == pytest.approx([w['weight'] for w in event['data']['worlds']])
        assert adapter.state.violations == []
    assert summarize(str(tmp_path))['percival_experiment'][config.percival_condition]['games'] == 3


def test_paired_configs_and_metrics():
    p0, p1 = [load_config(f'configs/arena/percival_{label}.yaml') for label in ['p0', 'p1']]
    for i in range(40):
        assert deal(p0, i) == deal(p1, i)
    assert p0.config_hash() != p1.config_hash()
    e = AvalonEngine()
    e.reset(ROLES, 0)
    assert vote_accuracy_metrics(e)['merlin_vote_accuracy_rank'] is None
    e.choose_team(0, [0, 1])
    e.vote_on_team({p: True for p in range(5)})
    assert vote_accuracy_metrics(e)['merlin_vote_accuracy_rank'] == 2
    summary = summarize_percival([{'percival_condition': 'four_world', 'winner': 'evil', 'quest_results': [False] * 3,
        'percival_metrics': {'assassination_reached': False, 'assassin_hit': False,
                             'merlin_vote_accuracy_rank': None, 'p_true_merlin': .6}}])['four_world']
    assert summary['assassin_accuracy'] is None
    assert summary['mean_p_true_merlin'] == .6


def test_legacy_hash_and_privacy():
    import hashlib
    import json
    from arena.config import NON_SEMANTIC_FIELDS
    config = load_config('configs/arena/sol_chat_only.yaml')
    old = config.dict(exclude=NON_SEMANTIC_FIELDS | {'percival_condition'})
    assert config.config_hash() == hashlib.sha256(json.dumps(old, sort_keys=True).encode()).hexdigest()[:16]
    e = AvalonEngine()
    e.reset(ROLES)
    p0 = PlayerMemory(0, e.get_private_info(0))
    p1 = PlayerMemory(0, e.get_private_info(0), percival_condition='four_world')
    assert p0.percival is None and p1.percival is not None
    for seat in [0, 1, 4]:
        memory = PlayerMemory(seat, e.get_private_info(seat))
        with pytest.raises(ValueError, match='Evil-only'):
            memory.observe('evil_chat', {'seq': 1, 'speaker': 2, 'text': 'private'})
    assert 'Your evil partner' not in p0.render_private()


@pytest.mark.parametrize('probabilities,expected', [
    ({'1': .7, '2': .3}, {1: .7, 2: .3}),
    ({'1': .7, '3': .3}, None),
    ({'1': .9, '2': .9}, None),
])
def test_p0_final_merlin_report_without_world_table(monkeypatch, probabilities, expected):
    import json
    for key in ['OPENAI_API_KEY', 'BOSON_API_KEY']:
        monkeypatch.delenv(key, raising=False)

    class ReportTransport:
        async def chat(self, payload):
            assert payload['tool_choice']['function']['name'] == 'report_merlin'
            return {'choices': [{'message': {'content': None, 'tool_calls': [{'function': {
                'name': 'report_merlin', 'arguments': json.dumps({'probabilities': probabilities})}}]}}]}

    e = AvalonEngine()
    e.reset(ROLES)
    a = LLMAgent(0, Role.PERCIVAL, condition='chat_only', transport=ReportTransport())
    a.set_private_info(e.get_private_info(0))
    assert a.memory.percival is None
    assert 'four-world' not in a._memory_context()
    assert asyncio.run(a.final_merlin_beliefs()) == expected
