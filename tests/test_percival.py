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
    # A better team exists, so only the cutoff decides (Percival is not the leader)
    a = make_agent()
    monkeypatch.setattr(a.memory.percival, 'all_good', lambda team: probability)
    monkeypatch.setattr(a.memory.percival, 'best_all_good', lambda size: 1.0)
    assert asyncio.run(a.vote_on_team(0, 0, 1, [0, 1])) is expected
    assert asyncio.run(a.vote_on_team(0, 4, 1, [0, 1])) is True
    h = make_agent(HeuristicAgent)
    monkeypatch.setattr(h.memory.percival, 'all_good', lambda team: probability)
    monkeypatch.setattr(h.memory.percival, 'best_all_good', lambda size: 1.0)
    assert h._decide_team_vote(0, [0, 1], leader=1)[0] is expected


# Hand-built evidence for Percival 0 with candidates 1 and 2, other seats 3 and 4.

def test_opening_clean_team_is_proposed_and_approved():
    b = PercivalBelief(0, [1, 2])
    # Every team with Percival on it is 50% all good, below the 0.55 cutoff
    assert b.all_good([0, 3]) == pytest.approx(0.5) and b.best_all_good(2) == pytest.approx(0.5)
    team = b.best_team(2)
    assert 0 in team and b.approves(team, leader=0) and b.approves(team, leader=1)
    assert b.approves([0, 4], leader=3)        # as good as the best team
    assert not b.approves([1, 3], leader=4)    # 25%: worse than the best team


def test_best_trio_below_cutoff_is_approved():
    # P1 seed 0: the clean trio sat at 48.9%, under the cutoff, and Percival rejected it
    b = PercivalBelief(0, [1, 2])
    b.update(entry('proposal', seq=1, leader=1, members=(1, 3)))
    b.update(entry('team_vote', seq=2, members=(1, 3), votes=((1, True), (2, False), (3, True), (4, False))))
    best = b.best_all_good(3)
    assert best < 0.55
    team = b.best_team(3)
    assert b.all_good(team) == pytest.approx(best) and b.approves(team, leader=4)
    worse = [t for t in ([0, 1, 3], [0, 2, 3], [0, 1, 4], [0, 2, 4], [0, 3, 4]) if b.all_good(t) < best - 1e-6]
    assert worse and not any(b.approves(t, leader=4) for t in worse)


def test_failed_quest_rules_out_its_members():
    b = PercivalBelief(0, [1, 2])
    b.update(entry('quest_result', seq=1, members=(0, 3), success=False, fails=1))  # 3 is evil
    assert b.best_team(2) == [0, 4] and b.all_good([0, 4]) == pytest.approx(1.0)
    assert not b.approves([0, 3], leader=4) and not b.approves([3, 4], leader=1)
    assert b.approves([0, 3], leader=0)  # a team Percival itself proposed is always backed


@pytest.mark.parametrize('seed', range(25))
def test_votes_back_own_proposals_on_random_evidence(seed):
    import random
    rng = random.Random(seed)
    b = PercivalBelief(0, [1, 2])
    truth = rng.choice(b.worlds)
    for seq in range(1, 13):
        size = rng.choice([2, 3])
        members = tuple(sorted(rng.sample(range(5), size)))
        kind = rng.choice(['proposal', 'team_vote', 'quest_result'])
        if kind == 'proposal':
            b.update(entry('proposal', seq=seq, leader=rng.randrange(5), members=members))
        elif kind == 'team_vote':
            votes = tuple((p, rng.random() < .5) for p in range(5))
            b.update(entry('team_vote', seq=seq, members=members, votes=votes))
        else:
            fails = len(truth.evil.intersection(members))
            b.update(entry('quest_result', seq=seq, members=members, success=fails == 0, fails=fails))
        for team_size in (2, 3):
            team = b.best_team(team_size)
            assert len(team) == team_size and b.approves(team, leader=0)
            assert all(b.approves(team, leader=other) for other in range(1, 5))


def test_agents_propose_the_best_team():
    a, h = make_agent(), make_agent(HeuristicAgent)
    for agent in (a, h):
        agent.memory.percival.update(entry('quest_result', seq=1, members=(0, 3), success=False, fails=1))
        assert asyncio.run(agent.propose_team(1, 2)) == [0, 4]
        assert asyncio.run(agent.vote_on_team(1, 0, 0, [0, 4])) is True
    assert 'The teams you would propose and approve: 2 players: [0, 4]' in a._memory_context()


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
    for key in ['OPENAI_API_KEY']:
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
    old = config.model_dump(exclude=NON_SEMANTIC_FIELDS | {'percival_condition'})
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
    for key in ['OPENAI_API_KEY']:
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
