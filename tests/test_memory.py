"""Unit tests for per-player memory, the knowledge graph, and beliefs (MEMORY_MODEL.md)."""

import asyncio
import json
import unittest
from typing import Any, Dict, List

from avalon.agents import HeuristicAgent
from avalon.belief_graph import PairBelief
from avalon.engine import AvalonEngine, Role
from avalon.llm_agent import LLMAgent
from avalon.memory import PlayerMemory
from avalon.runner import AvalonGameRunner


ROLES = {0: Role.LOYAL_SERVANT, 1: Role.MINION, 2: Role.MERLIN, 3: Role.ASSASSIN, 4: Role.LOYAL_SERVANT}


def servant_memory(owner: int = 0, belief_mode: str = "rule") -> PlayerMemory:
    engine = AvalonEngine(seed=0)
    engine.reset(preset_roles=ROLES)
    return PlayerMemory(owner, engine.get_private_info(owner), belief_mode=belief_mode)


class Feed:
    """Delivers events to one memory with increasing seq numbers."""

    def __init__(self, memory: PlayerMemory):
        self.memory = memory
        self.seq = 0

    def send(self, event_type: str, **data: Any) -> int:
        self.seq += 1
        self.memory.observe(event_type, dict(data, seq=self.seq))
        return self.seq

    def say(self, turn: int, round_num: int, speaker: int, text: str) -> int:
        return self.send("utterance", turn=turn, round_num=round_num, speaker=speaker, text=text)

    def team(self, turn: int, round_num: int, leader: int, team: List[int], votes: Dict[int, bool]) -> None:
        self.send("team_proposed", turn=turn, round_num=round_num, leader=leader, team=team)
        approved = sum(votes.values()) > 2
        self.send("team_vote_result", turn=turn, round_num=round_num, leader=leader, team=team, votes=votes, approved=approved)

    def quest(self, turn: int, round_num: int, team: List[int], fails: int) -> None:
        self.send("quest_result", turn=turn, round_num=round_num, team=team, success=fails == 0, num_fails=fails)


def doc_example(memory: PlayerMemory) -> Feed:
    """The worked example from MEMORY_MODEL.md, from Servant P0's point of view."""
    feed = Feed(memory)
    for p in range(5):
        feed.say(0, 0, p, "Let's be careful on the first quest.")
    feed.team(0, 0, 1, [1, 3], {0: True, 1: True, 2: False, 3: True, 4: False})
    feed.quest(0, 0, [1, 3], fails=1)
    feed.say(1, 0, 2, "Player 1 approved the failed team, I don't trust Player 1.")
    feed.say(1, 0, 0, "P1 and P3 owe us an explanation.")
    feed.say(1, 0, 1, "Player 3 is fine, Q1 was bad luck.")
    accusation = feed.say(1, 0, 4, "Player 2's team looks too convenient, suspicious.")
    feed.team(1, 0, 2, [0, 2, 4], {0: True, 1: False, 2: True, 3: False, 4: True})
    feed.quest(1, 0, [0, 2, 4], fails=0)
    feed.accusation_seq = accusation
    return feed


class TestPairBelief(unittest.TestCase):
    def test_prior_is_uniform_and_sums_to_two(self):
        belief = PairBelief(owner=0)
        self.assertEqual(len(belief.all_pairs), 6)
        for p in (1, 2, 3, 4):
            self.assertAlmostEqual(belief.p_evil[p], 0.5)

    def test_rule_matches_worked_example(self):
        memory = servant_memory()
        doc_example(memory)
        p = memory.beliefs.p_evil
        self.assertAlmostEqual(p[1], 0.75)
        self.assertAlmostEqual(p[3], 0.75)
        self.assertAlmostEqual(p[2], 0.25)
        self.assertAlmostEqual(p[4], 0.25)
        self.assertAlmostEqual(sum(p.values()), 2.0)
        self.assertEqual(memory.beliefs.validate(p), [])

    def test_passed_quest_changes_nothing(self):
        memory = servant_memory()
        feed = Feed(memory)
        feed.team(0, 0, 1, [1, 3], {p: True for p in range(5)})
        feed.quest(0, 0, [1, 3], fails=0)
        for p in (1, 2, 3, 4):
            self.assertAlmostEqual(memory.beliefs.p_evil[p], 0.5)

    def test_owner_on_failed_two_person_team_forces_partner(self):
        memory = servant_memory()
        feed = Feed(memory)
        feed.team(0, 0, 0, [0, 3], {p: True for p in range(5)})
        feed.quest(0, 0, [0, 3], fails=1)
        never, always = memory.beliefs.forced()
        self.assertEqual(always, [3])
        self.assertEqual(never, [])
        self.assertAlmostEqual(memory.beliefs.p_evil[3], 1.0)

    def test_two_fails_force_both_members(self):
        memory = servant_memory()
        feed = Feed(memory)
        feed.team(0, 0, 1, [1, 2, 3], {p: True for p in range(5)})
        feed.quest(0, 0, [1, 2, 3], fails=2)
        never, _ = memory.beliefs.forced()
        self.assertEqual(never, [4])
        self.assertAlmostEqual(memory.beliefs.p_evil[4], 0.0)

    def test_validate_rejects_incoherent_values(self):
        memory = servant_memory()
        doc_example(memory)
        # The original spec's example numbers sum to 1.70
        errors = memory.beliefs.validate({1: 0.60, 2: 0.25, 3: 0.55, 4: 0.30})
        self.assertTrue(any("sum to 2" in e for e in errors))
        errors = memory.beliefs.validate({1: 0.2, 2: 0.9, 3: 0.2, 4: 0.7})
        self.assertTrue(any("at least 1" in e for e in errors))
        self.assertTrue(memory.beliefs.validate({1: 1.0, 2: 1.0}))

    def test_three_person_team_constraint(self):
        memory = servant_memory()
        feed = Feed(memory)
        feed.team(1, 0, 1, [1, 2, 3], {p: True for p in range(5)})
        feed.quest(1, 0, [1, 2, 3], fails=1)
        errors = memory.beliefs.validate({1: 0.3, 2: 0.3, 3: 0.3, 4: 1.1})
        self.assertTrue(any("between 0 and 1" in e for e in errors))
        errors = memory.beliefs.validate({1: 0.3, 2: 0.3, 3: 0.3, 4: 1.0})
        self.assertTrue(any("sum to at least 1" in e for e in errors))


class TestKnowledgeGraph(unittest.TestCase):
    def test_contradiction_flag_and_table(self):
        memory = servant_memory()
        feed = doc_example(memory)
        added, dropped = memory.add_talk_edges([
            {"type": "accused", "from": 4, "to": 2, "sources": [feed.accusation_seq], "quote": "P2's team looks too convenient"},
        ])
        self.assertEqual((len(added), dropped), (1, 0))

        flags = memory.graph.contradictions()
        self.assertEqual(len(flags), 1)
        talk, vote = flags[0]
        self.assertEqual((talk.src, talk.dst, vote.type, vote.dst), (4, 2, "voted_approve", "Q2.1"))

        table = memory.render_table()
        self.assertIn("Constraints: Q1.1 {1,3} → 1 fail (at least 1 of P1, P3 is evil)", table)
        self.assertIn("P1 | 0.75 | proposed, approved Q1.1; on Q1.1 (fail); rejected Q2.1", table)
        self.assertIn(f"accused P2 (#{feed.accusation_seq}) ⚠ then approved Q2.1", table)
        self.assertIn("Your record:", table)

    def test_talk_edges_must_cite_the_speakers_own_lines(self):
        memory = servant_memory()
        feed = doc_example(memory)
        _, dropped = memory.add_talk_edges([
            {"type": "accused", "from": 2, "to": 1, "sources": [feed.accusation_seq]},  # line was spoken by P4
            {"type": "accused", "from": 4, "to": 2, "sources": [999]},  # not in this player's log
            {"type": "accused", "from": 4, "to": 4, "sources": [feed.accusation_seq]},  # self-accusation
            {"type": "backed_team", "from": 4, "to": "Q9.9", "sources": [feed.accusation_seq]},  # unknown team
            {"type": "claimed_role", "from": 4, "role": "King", "sources": [feed.accusation_seq]},  # not a role
            {"type": "gossip", "from": 4, "to": 2, "sources": [feed.accusation_seq]},
        ])
        self.assertEqual(dropped, 6)
        self.assertEqual(memory.graph.edges_of(("accused", "backed_team", "claimed_role")), [])

    def test_quotes_and_notes_are_clipped(self):
        memory = servant_memory()
        feed = doc_example(memory)
        added, _ = memory.add_talk_edges([
            {"type": "accused", "from": 4, "to": 2, "sources": [feed.accusation_seq], "quote": " ".join(["word"] * 30)},
        ])
        self.assertEqual(len(added[0].quote.split()), 10)
        memory.set_notes({"1": " ".join(["x"] * 40), "0": "about myself", "9": "nobody"})
        self.assertEqual(len(memory.notes[1].split()), 15)
        self.assertNotIn(0, memory.notes)
        self.assertNotIn(9, memory.notes)

    def test_own_utterances_become_self_edges(self):
        memory = servant_memory()
        doc_example(memory)
        said = memory.graph.edges_of(("i_said",))
        self.assertEqual(len(said), 2)
        self.assertTrue(all(e.src == 0 for e in said))

    def test_tts_tags_are_stripped_from_the_log(self):
        memory = servant_memory()
        Feed(memory).say(0, 0, 1, "<|emotion:anger|><|prosody:expressiveness_high|>Hold on! <|prosody:pause|>Why?")
        self.assertEqual(memory.log[0].text, "Hold on! Why?")

    def test_recall_tools(self):
        memory = servant_memory()
        feed = doc_example(memory)
        self.assertIn("P4:", memory.run_tool("quote", {"seq": feed.accusation_seq}))
        self.assertIn("no entry", memory.run_tool("quote", {"seq": 999}))
        votes = memory.recall(player=3, kinds=["team_vote"])
        self.assertEqual(len(votes), 2)
        self.assertIn("proposed", memory.run_tool("evidence", {"player": 1}))
        self.assertIn("you said", memory.run_tool("my_record", {}))

    def test_evil_chat_cannot_reach_good_players(self):
        memory = servant_memory()
        with self.assertRaises(ValueError):
            Feed(memory).send("evil_chat", turn=3, round_num=0, speaker=1, text="Merlin is P2")


def evil_memory(owner: int = 1, merlin_graph: bool = True) -> PlayerMemory:
    """Minion P1 (partner: Assassin P3). Good players: P0, P2 (Merlin), P4."""
    engine = AvalonEngine(seed=0)
    engine.reset(preset_roles=ROLES)
    return PlayerMemory(owner, engine.get_private_info(owner), merlin_graph=merlin_graph)


class TestMerlinBelief(unittest.TestCase):
    def test_off_by_default_and_never_for_good_players(self):
        self.assertIsNone(evil_memory(merlin_graph=False).merlin)
        engine = AvalonEngine(seed=0)
        engine.reset(preset_roles=ROLES)
        self.assertIsNone(PlayerMemory(0, engine.get_private_info(0), merlin_graph=True).merlin)

    def test_starts_uniform_over_good_players(self):
        memory = evil_memory()
        self.assertEqual(sorted(memory.merlin.p_merlin), [0, 2, 4])
        for v in memory.merlin.p_merlin.values():
            self.assertAlmostEqual(v, 1 / 3)

    def test_accurate_voter_stands_out(self):
        memory = evil_memory()
        feed = Feed(memory)
        # P2 rejects every team with evil on it and approves the clean one; P0 and P4 approve everything
        feed.team(0, 0, 0, [0, 1], {0: True, 1: True, 2: False, 3: True, 4: True})
        feed.quest(0, 0, [0, 1], fails=0)
        feed.team(1, 0, 1, [1, 3, 4], {0: True, 1: True, 2: False, 3: True, 4: True})
        feed.quest(1, 0, [1, 3, 4], fails=1)
        feed.team(2, 0, 2, [0, 2], {0: True, 1: False, 2: True, 3: False, 4: True})
        feed.quest(2, 0, [0, 2], fails=0)
        p = memory.merlin.p_merlin
        self.assertAlmostEqual(sum(p.values()), 1.0)
        self.assertEqual(memory.merlin.top(), 2)
        self.assertGreater(p[2], 0.5)
        self.assertIn("P(Merlin)", memory.render_table())

    def test_decisive_reject_counts_extra(self):
        memory = evil_memory()
        feed = Feed(memory)
        # Two approvals, so each reject was decisive; P2 and P4 both reject a team with evil
        feed.team(0, 0, 0, [0, 3], {0: True, 1: True, 2: False, 3: False, 4: False})
        p = memory.merlin.p_merlin
        self.assertAlmostEqual(p[2], p[4])
        self.assertGreater(p[2], p[0] * 1.5 ** 2 * 1.4)

    def test_hammer_votes_carry_no_signal(self):
        memory = evil_memory()
        feed = Feed(memory)
        feed.team(0, 4, 0, [0, 3], {0: True, 1: True, 2: False, 3: True, 4: True})
        for v in memory.merlin.p_merlin.values():
            self.assertAlmostEqual(v, 1 / 3)

    def test_early_accusation_counts_once_and_only_before_exposure(self):
        memory = evil_memory()
        feed = Feed(memory)
        first = feed.say(0, 0, 4, "Player 3 is suspicious.")
        again = feed.say(0, 0, 4, "Still suspicious of Player 3.")
        memory.add_talk_edges([
            {"type": "accused", "from": 4, "to": 3, "sources": [first]},
            {"type": "accused", "from": 4, "to": 3, "sources": [again]},
        ])
        p = memory.merlin.p_merlin
        self.assertAlmostEqual(p[4] / p[0], 2.0)

        # P3 is exposed by a failed quest; accusing them afterwards is not evidence of Merlin
        feed.team(0, 0, 0, [0, 3], {q: True for q in range(5)})
        feed.quest(0, 0, [0, 3], fails=1)
        late = feed.say(1, 0, 0, "Player 3 failed that quest.")
        memory.add_talk_edges([{"type": "accused", "from": 0, "to": 3, "sources": [late]}])
        p = memory.merlin.p_merlin
        self.assertAlmostEqual(p[4] / p[0], 2.0)


class SecretHeuristicAgent(HeuristicAgent):
    """Writes a unique marker into its own reasoning, so leaks are detectable."""

    def _record_reason(self, turn, round_num, action, reason):
        super()._record_reason(turn, round_num, action, f"{reason} secret-{self.player_id}")

    async def after_discussion(self, turn, round_num):
        await super().after_discussion(turn, round_num)
        if self.memory is not None:
            self.memory.add_free_note(f"note secret-{self.player_id}")
            self.memory.set_notes({(self.player_id + 1) % 5: f"read secret-{self.player_id}"})


def run_game(agent_cls, condition: str, seed: int, **agent_kwargs):
    agents = {i: agent_cls(player_id=i, role=Role.LOYAL_SERVANT, condition=condition, seed=seed * 10 + i, **agent_kwargs) for i in range(5)}
    runner = AvalonGameRunner(agents=agents, seed=seed, tts_client=None, verbose=False)
    metrics = asyncio.run(runner.run_game())
    return runner, agents, metrics


class TestIsolation(unittest.TestCase):
    def test_no_player_sees_another_players_thinking(self):
        for condition in ("chat_only", "belief_graph", "rule_graph"):
            for seed in range(6):
                runner, agents, _ = run_game(SecretHeuristicAgent, condition, seed)
                for p, agent in agents.items():
                    text = agent.memory.all_text()
                    self.assertIn(f"secret-{p}", text)
                    for q in agents:
                        if q != p:
                            self.assertNotIn(f"secret-{q}", text, f"P{q}'s thinking leaked to P{p} ({condition}, seed {seed})")

    def test_every_edge_cites_the_owners_own_log(self):
        for seed in range(6):
            runner, agents, _ = run_game(HeuristicAgent, "rule_graph", seed)
            for p, agent in agents.items():
                seqs = {e.seq for e in agent.memory.log}
                for edge in agent.memory.graph.edges:
                    self.assertTrue(set(edge.sources) <= seqs, f"P{p} edge {edge} cites entries it never saw")
                    if edge.type in ("i_said", "i_reasoned"):
                        self.assertEqual(edge.src, p)

    def test_private_channels(self):
        saw_evil_chat = False
        for seed in range(20):
            runner, agents, _ = run_game(HeuristicAgent, "rule_graph", seed)
            evil = set(runner.engine.get_evil_players())
            for p, agent in agents.items():
                kinds = {e.kind for e in agent.memory.log}
                if p not in evil:
                    self.assertNotIn("evil_chat", kinds)
                saw_evil_chat |= "evil_chat" in kinds
                for record in runner.engine.quest_history:
                    on_team = p in record.team
                    self.assertEqual(record.turn + 1 in agent.memory.private.my_quest_cards, on_team)
        self.assertTrue(saw_evil_chat, "no seed reached the assassination; widen the seed range")

    def test_memories_are_separate_objects(self):
        _, agents, _ = run_game(HeuristicAgent, "rule_graph", 1)
        logs = [id(a.memory.log) for a in agents.values()]
        entries = [id(a.memory.log[0]) for a in agents.values()]
        self.assertEqual(len(set(logs)), 5)
        self.assertEqual(len(set(entries)), 5)


class TestConditions(unittest.TestCase):
    def test_only_servants_hold_beliefs(self):
        runner, agents, metrics = run_game(HeuristicAgent, "rule_graph", 3)
        servants = {p for p, a in agents.items() if a.role == Role.LOYAL_SERVANT}
        self.assertEqual(set(metrics.final_p_evil), servants)
        for p_evil in metrics.final_p_evil.values():
            self.assertAlmostEqual(sum(p_evil.values()), 2.0)

    def test_condition_a_servants_do_not_use_the_graph(self):
        _, agents, _ = run_game(HeuristicAgent, "chat_only", 2)
        for agent in agents.values():
            if agent.role == Role.LOYAL_SERVANT:
                self.assertIsNone(agent.suspicion((agent.player_id + 1) % 5))
                self.assertEqual(agent.memory.graph.edges_of(("accused", "defended")), [])

    def test_evil_is_identical_without_the_merlin_graph(self):
        _, agents, metrics = run_game(HeuristicAgent, "rule_graph", 5)
        self.assertIsNone(metrics.assassin_p_merlin)
        for agent in agents.values():
            if not agent.side:
                self.assertIsNone(agent.memory.merlin)
                self.assertEqual(agent.memory.graph.edges_of(("accused", "defended")), [])

    def test_assassin_uses_its_merlin_graph(self):
        checked = 0
        for seed in range(30):
            runner, agents, metrics = run_game(HeuristicAgent, "rule_graph", seed, merlin_graph=True)
            if metrics.assassination_target is None:
                continue
            p = metrics.assassin_p_merlin
            self.assertAlmostEqual(sum(p.values()), 1.0)
            self.assertEqual(sorted(p), sorted(runner.engine.get_good_players()))
            self.assertEqual(metrics.assassination_target, agents[metrics.assassin_id].memory.merlin.top())
            checked += 1
        self.assertGreater(checked, 0, "no seed reached the assassination; widen the seed range")

    def test_llm_agents_run_without_an_api_key(self):
        for condition in ("chat_only", "belief_graph", "rule_graph"):
            agents = {i: LLMAgent(player_id=i, role=Role.LOYAL_SERVANT, condition=condition, seed=i) for i in range(5)}
            for agent in agents.values():
                agent.api_key = ""  # never reach a real endpoint, even if a key is set in the environment
            runner = AvalonGameRunner(agents=agents, seed=4, tts_client=None, verbose=False)
            metrics = asyncio.run(runner.run_game())
            self.assertTrue(metrics.final_p_evil)
            if condition == "belief_graph":
                self.assertTrue(all(n > 0 for n in metrics.belief_fallbacks.values()))


class StubLLMAgent(LLMAgent):
    """LLMAgent whose tool calls return canned answers, in order."""

    def __init__(self, *args, answers=None, **kwargs):
        super().__init__(*args, api_key="test", **kwargs)
        self.answers = list(answers or [])
        self.prompts: List[str] = []

    async def _call_llm_tool(self, user_prompt, tool_name):
        self.prompts.append(user_prompt)
        return self.answers.pop(0) if self.answers else {}


def stub_servant(answers, condition="belief_graph") -> StubLLMAgent:
    engine = AvalonEngine(seed=0)
    engine.reset(preset_roles=ROLES)
    agent = StubLLMAgent(player_id=0, role=Role.LOYAL_SERVANT, condition=condition, answers=answers)
    agent.set_private_info(engine.get_private_info(0))
    return agent


class TestExtraction(unittest.TestCase):
    def _speak(self, agent):
        feed = Feed(agent.memory)
        feed.team(0, 0, 1, [1, 3], {0: True, 1: True, 2: False, 3: True, 4: False})
        feed.quest(0, 0, [1, 3], fails=1)
        return feed.say(1, 0, 4, "I don't trust Player 2 at all.")

    def test_valid_extraction_is_applied(self):
        agent = stub_servant([])
        seq = self._speak(agent)
        agent.answers = [{
            "edges": [{"type": "accused", "from": 4, "to": 2, "sources": [seq], "quote": "I don't trust Player 2"}],
            "notes": {"4": "suspicious of P2"},
            "p_evil": {"1": 0.8, "2": 0.2, "3": 0.7, "4": 0.3},
        }]
        asyncio.run(agent.after_discussion(1, 0))
        self.assertEqual(agent.memory.beliefs.source, "llm")
        self.assertAlmostEqual(agent.memory.beliefs.p_evil[1], 0.8)
        self.assertEqual(len(agent.memory.graph.edges_of(("accused",))), 1)
        self.assertEqual(agent.memory.notes[4], "suspicious of P2")
        self.assertEqual(agent.memory.belief_fallbacks, 0)

    def test_invalid_beliefs_are_retried_once_with_the_errors(self):
        agent = stub_servant([])
        self._speak(agent)
        agent.answers = [
            {"edges": [], "notes": {}, "p_evil": {"1": 0.6, "2": 0.25, "3": 0.55, "4": 0.3}},
            {"edges": [], "notes": {}, "p_evil": {"1": 0.7, "2": 0.3, "3": 0.7, "4": 0.3}},
        ]
        asyncio.run(agent.after_discussion(1, 0))
        self.assertIn("sum to 2", agent.prompts[1])
        self.assertEqual(agent.memory.beliefs.source, "llm")
        self.assertEqual(agent.memory.belief_fallbacks, 0)

    def test_second_failure_falls_back_to_the_rule(self):
        agent = stub_servant([])
        self._speak(agent)
        bad = {"edges": [], "notes": {}, "p_evil": {"1": 0.1, "2": 0.9, "3": 0.1, "4": 0.9}}
        agent.answers = [bad, bad]
        asyncio.run(agent.after_discussion(1, 0))
        self.assertEqual(agent.memory.beliefs.source, "rule")
        self.assertEqual(agent.memory.belief_fallbacks, 1)

    def test_condition_c_ignores_llm_beliefs(self):
        agent = stub_servant([], condition="rule_graph")
        self._speak(agent)
        agent.answers = [{"edges": [], "notes": {}, "p_evil": {"1": 0.9, "2": 0.1, "3": 0.9, "4": 0.1}}]
        asyncio.run(agent.after_discussion(1, 0))
        self.assertEqual(agent.memory.beliefs.source, "rule")
        self.assertEqual(len(agent.prompts), 1)
        self.assertIn("Leave out p_evil", agent.prompts[0])

    def test_new_failed_quest_resets_beliefs_that_break_it(self):
        agent = stub_servant([])
        feed = Feed(agent.memory)
        self.assertEqual(agent.memory.apply_llm_beliefs({"1": 0.1, "2": 0.9, "3": 0.1, "4": 0.9}), [])
        feed.team(0, 0, 1, [1, 3], {p: True for p in range(5)})
        feed.quest(0, 0, [1, 3], fails=1)
        self.assertEqual(agent.memory.beliefs.source, "rule")
        self.assertEqual(agent.memory.constraint_resets, 1)


def tool_call(call_id: str, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def reply(*calls: Dict[str, Any]) -> Dict[str, Any]:
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": list(calls)}}]}


class FakeAPIAgent(LLMAgent):
    """LLMAgent whose HTTP calls return scripted responses and are recorded."""

    def __init__(self, *args, responses=None, **kwargs):
        super().__init__(*args, api_key="test", **kwargs)
        self.responses = list(responses or [])
        self.payloads: List[Dict[str, Any]] = []

    async def _post(self, payload):
        self.payloads.append(json.loads(json.dumps(payload)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def fake_api_servant(responses, condition="belief_graph") -> FakeAPIAgent:
    engine = AvalonEngine(seed=0)
    engine.reset(preset_roles=ROLES)
    agent = FakeAPIAgent(player_id=0, role=Role.LOYAL_SERVANT, condition=condition, responses=responses)
    agent.set_private_info(engine.get_private_info(0))
    doc_example(agent.memory)
    return agent


class TestRecallLoop(unittest.TestCase):
    def test_recall_result_comes_from_own_memory_before_acting(self):
        agent = fake_api_servant([
            reply(tool_call("c1", "quote", {"seq": 12})),
            reply(tool_call("c2", "vote_on_team", {"approve": False, "reason": "P4 flip-flopped on P2"})),
        ])
        approve = asyncio.run(agent.vote_on_team(turn=2, round_num=0, leader=3, team=[3, 4]))
        self.assertFalse(approve)

        first, second = agent.payloads
        self.assertEqual(first["tool_choice"], "required")
        offered = {t["function"]["name"] for t in first["tools"]}
        self.assertEqual(offered, {"vote_on_team", "recall", "quote", "evidence", "my_record"})
        tool_msg = second["messages"][-1]
        self.assertEqual((tool_msg["role"], tool_msg["tool_call_id"]), ("tool", "c1"))
        self.assertIn("Player 2's team looks too convenient", tool_msg["content"])

        reasons = agent.memory.graph.edges_of(("i_reasoned",))
        self.assertEqual((reasons[-1].action, reasons[-1].reason), ("rejected", "P4 flip-flopped on P2"))

    def test_recall_steps_are_capped_then_the_action_is_forced(self):
        agent = fake_api_servant([
            reply(tool_call("c1", "recall", {"player": 4})),
            reply(tool_call("c2", "evidence", {"player": 4})),
            reply(tool_call("c3", "vote_on_team", {"approve": True})),
        ])
        self.assertTrue(asyncio.run(agent.vote_on_team(turn=2, round_num=0, leader=3, team=[3, 4])))
        self.assertEqual(len(agent.payloads), 3)
        self.assertEqual(agent.payloads[2]["tool_choice"], {"type": "function", "function": {"name": "vote_on_team"}})

    def test_provider_without_required_falls_back_to_forced_tool(self):
        agent = fake_api_servant([
            RuntimeError("LLM API Error (400): tool_choice 'required' not supported"),
            reply(tool_call("c1", "vote_on_team", {"approve": True})),
        ])
        self.assertTrue(asyncio.run(agent.vote_on_team(turn=2, round_num=0, leader=3, team=[3, 4])))
        self.assertEqual(agent.payloads[1]["tool_choice"]["type"], "function")

    def test_condition_a_gets_no_recall_tools_and_its_full_log(self):
        agent = fake_api_servant([reply(tool_call("c1", "vote_on_team", {"approve": True}))], condition="chat_only")
        asyncio.run(agent.vote_on_team(turn=2, round_num=0, leader=3, team=[3, 4]))
        payload = agent.payloads[0]
        self.assertEqual([t["function"]["name"] for t in payload["tools"]], ["vote_on_team"])
        prompt = payload["messages"][1]["content"]
        self.assertIn("Everything you have observed", prompt)
        self.assertIn("#1 [Q1.1]", prompt)
        self.assertNotIn("P(evil)", prompt)

    def test_graph_conditions_see_the_table_not_another_players_thinking(self):
        agent = fake_api_servant([reply(tool_call("c1", "vote_on_team", {"approve": True}))], condition="rule_graph")
        asyncio.run(agent.vote_on_team(turn=2, round_num=0, leader=3, team=[3, 4]))
        prompt = agent.payloads[0]["messages"][1]["content"]
        self.assertIn("Player | P(evil) | Actions | Talk", prompt)
        self.assertIn("P1 | 0.75", prompt)
        self.assertIn("You are Player 0, Loyal Servant (Good).", prompt)


class TestFullGameWithScriptedLLM(unittest.TestCase):
    """A whole game where every Servant's extraction returns valid beliefs from its own rule table."""

    def test_condition_b_game_keeps_llm_beliefs_coherent(self):
        class CoherentLLM(LLMAgent):
            async def _call_llm_tool(self, user_prompt, tool_name):
                if tool_name == "record_observations" and self.memory.beliefs is not None:
                    rule = self.memory.beliefs.rule_marginals()
                    return {"edges": [], "notes": {}, "p_evil": {str(p): v for p, v in rule.items()}}
                return {}

        agents = {i: CoherentLLM(player_id=i, role=Role.LOYAL_SERVANT, condition="belief_graph", seed=i) for i in range(5)}
        for agent in agents.values():
            agent.api_key = ""
        metrics = asyncio.run(AvalonGameRunner(agents=agents, seed=7, tts_client=None, verbose=False).run_game())
        self.assertEqual(set(metrics.belief_fallbacks.values()), {0})
        for p, p_evil in metrics.final_p_evil.items():
            self.assertEqual(agents[p].memory.beliefs.source, "llm")
            self.assertEqual(agents[p].memory.beliefs.validate(p_evil), [])


if __name__ == "__main__":
    unittest.main()
