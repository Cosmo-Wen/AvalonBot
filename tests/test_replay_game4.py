"""
Reenacts the recorded pilot game 4 (experiments/avalon-llm-haiku-pilot/game4-all-fixes) through
each player's own memory and checks the knowledge graphs it builds.

Seats: P0 Merlin, P1 Assassin, P2 and P3 Loyal Servants, P4 Minion. First leader P3.
Quests: Q1 [0,2] pass, Q2 [0,2,3] fail (1), Q3 [1,4] fail (2), Q4 [1,2,4] fail (2). Evil wins.
In Q2 the Servant P3 played Fail, which the rules don't allow; the evidence of every other
player is therefore self-contradictory, which these tests rely on.
"""

import os

import pytest

from avalon.belief_graph import PairBelief
from avalon.engine import Role
from avalon.replay import load_events, load_talk_edges, replay_arena_game
from avalon.visualize import build_data, render_html

GAME_DIR = os.path.join(
    os.path.dirname(__file__), "..", "experiments", "avalon-llm-haiku-pilot", "game4-all-fixes"
)
EVENTS = load_events(os.path.join(GAME_DIR, "games", "game_00000.jsonl"))
TALK_EDGES = load_talk_edges(os.path.join(GAME_DIR, "talk_edges.json"))

MERLIN, ASSASSIN, SERVANT_A, SERVANT_B, MINION = 0, 1, 2, 3, 4
Q2_FAILED = 195  # seq of the Q2 quest result
Q3_FAILED = 347


@pytest.fixture(scope="module")
def game():
    return replay_arena_game(EVENTS, TALK_EDGES)


class TestReenactment:
    def test_roles_and_outcome(self, game):
        assert game.roles == {
            0: Role.MERLIN, 1: Role.ASSASSIN, 2: Role.LOYAL_SERVANT, 3: Role.LOYAL_SERVANT, 4: Role.MINION,
        }
        assert game.first_leader == 3
        assert game.true_evil == [1, 4]
        assert game.good_won is False

    def test_only_rule_break_is_the_servant_fail_card(self, game):
        # Leader rotation, team sizes, majority votes and the Q4.5 hammer all match the engine.
        assert game.violations == ["Q2 quest: Player 3 (LOYAL_SERVANT) is good but played Fail"]

    def test_every_player_logs_the_same_public_game(self, game):
        logs = {seat: [(e.seq, e.kind) for e in m.log] for seat, m in game.memories.items()}
        assert len(set(map(tuple, logs.values()))) == 1
        kinds = [kind for _, kind in logs[0]]
        assert kinds.count("utterance") == 70
        assert kinds.count("proposal") == 14
        assert kinds.count("team_vote") == 14
        assert kinds.count("quest_result") == 4

    def test_graph_has_every_team_with_votes_and_results(self, game):
        graph = game.memories[SERVANT_A].graph
        assert len(graph.teams) == 14
        assert list(graph.teams["Q1.4"].members) == [0, 2] and graph.teams["Q1.4"].approved
        assert graph.teams["Q4.5"].approved  # 2 approvals, passed only by the hammer
        assert [t.label for t in graph.failed_teams()] == ["Q2.1", "Q3.4", "Q4.5"]
        assert [(t.label, t.fails) for t in graph.failed_teams()] == [("Q2.1", 1), ("Q3.4", 2), ("Q4.5", 2)]
        assert graph.teams["Q3.4"].votes == {0: False, 1: True, 2: True, 3: False, 4: True}

    def test_every_annotated_talk_edge_is_in_every_graph(self, game):
        for memory in game.memories.values():
            talk = memory.graph.edges_of(("accused", "defended"))
            assert len(talk) == len(TALK_EDGES)

    def test_every_annotated_quote_is_in_the_line_it_cites(self, game):
        memory = game.memories[MERLIN]
        for raw in TALK_EDGES:
            lines = [memory.quote(seq) for seq in raw["sources"]]
            assert all(line.speaker == raw["from"] for line in lines), raw
            assert any(raw["quote"] in line.text for line in lines), raw

    def test_talk_edge_citing_someone_elses_line_is_rejected(self):
        bad = {"type": "accused", "from": 2, "to": 1, "sources": [44], "quote": "P0 said this"}
        with pytest.raises(ValueError, match="does not cite"):
            replay_arena_game(EVENTS, [bad])


class TestIsolation:
    def test_quest_cards_reach_only_the_player_who_played_them(self, game):
        cards = {seat: m.private.my_quest_cards for seat, m in game.memories.items()}
        assert cards[MERLIN] == {1: True, 2: True}
        assert cards[ASSASSIN] == {3: False, 4: False}
        assert cards[SERVANT_A] == {1: True, 2: True, 4: True}
        assert cards[SERVANT_B] == {2: False}
        assert cards[MINION] == {3: False, 4: False}

    def test_private_role_knowledge(self, game):
        seen = {seat: m.private.seen_evil for seat, m in game.memories.items()}
        assert seen == {0: (1, 4), 1: (4,), 2: (), 3: (), 4: (1,)}

    def test_only_servants_hold_p_evil_and_only_evil_holds_p_merlin(self, game):
        for seat, memory in game.memories.items():
            assert (memory.beliefs is not None) == (seat in (SERVANT_A, SERVANT_B))
            assert (memory.merlin is not None) == (seat in (ASSASSIN, MINION))


class TestServantBeliefs:
    def test_after_q2_servant_p2_wrongly_suspects_p0_and_p3(self):
        game = replay_arena_game(EVENTS, TALK_EDGES, stop_after_seq=Q2_FAILED)
        beliefs = game.memories[SERVANT_A].beliefs
        assert beliefs.consistent
        assert beliefs.p_evil == pytest.approx({0: 0.6, 1: 0.4, 3: 0.6, 4: 0.4})
        assert beliefs.validate(dict(beliefs.p_evil)) == []

    def test_after_q2_servant_p3_knows_the_fail_was_its_own(self):
        game = replay_arena_game(EVENTS, TALK_EDGES, stop_after_seq=Q2_FAILED)
        memory = game.memories[SERVANT_B]
        assert memory.beliefs.failed_quests == []
        assert memory.beliefs.p_evil == pytest.approx({0: 0.5, 1: 0.5, 2: 0.5, 4: 0.5})
        assert memory.graph.render_constraints() == ["Constraints: Q2.1 {0,2,3} → 1 fail (all played by you)"]

    def test_q3_contradicts_q2_for_p2_and_no_pair_is_ruled_out_yet(self):
        game = replay_arena_game(EVENTS, TALK_EDGES, stop_after_seq=Q3_FAILED)
        beliefs = game.memories[SERVANT_A].beliefs
        assert not beliefs.consistent
        # {1,4} fits Q3; every pair with P0 or P3 fits Q2 instead. Tie, so all stay possible.
        assert (1, 4) in beliefs.possible_pairs()
        assert len(beliefs.possible_pairs()) == 6
        assert beliefs.validate(dict(beliefs.p_evil)) == []

    def test_final_servant_beliefs_find_both_evil_players(self, game):
        for seat in (SERVANT_A, SERVANT_B):
            beliefs = game.memories[seat].beliefs
            assert beliefs.possible_pairs() == [(1, 4)]
            assert beliefs.p_evil[ASSASSIN] == 1.0 and beliefs.p_evil[MINION] == 1.0
            assert beliefs.validate(dict(beliefs.p_evil)) == []
        assert not game.memories[SERVANT_A].beliefs.consistent  # still sees the illegal Q2 fail
        assert game.memories[SERVANT_B].beliefs.consistent  # explained Q2 with its own card

    def test_graph_beats_what_the_servants_reported_in_the_game(self, game):
        for seat in (SERVANT_A, SERVANT_B):
            scores = game.rule_vs_reported_brier(seat)
            assert scores["graph"] == 0.0
            assert scores["reported"] > 0.1


class TestContradictionFlags:
    def flags(self, game, owner=SERVANT_A):
        return {(t.src, t.dst, t.seq, v.dst) for t, v in game.memories[owner].graph.contradictions()}

    def test_p3_accused_then_approved(self, game):
        flags = self.flags(game)
        assert (3, 2, 316, "Q4.4") in flags  # "Player 2 was on the failed quest" → approved [0,2,3]
        assert (3, 0, 203, "Q4.4") in flags
        assert (3, 4, 470, "Q4.5") in flags  # "1 and 4 backed it" → approved [1,2,4]
        assert (3, 2, 505, "Q4.5") in flags

    def test_nobody_else_contradicts_themselves(self, game):
        assert {src for src, *_ in self.flags(game)} == {3}

    def test_flags_are_the_same_in_every_graph(self, game):
        assert all(self.flags(game, seat) == self.flags(game) for seat in game.memories)


class TestEvilMerlinGraph:
    def test_both_evil_players_rank_true_merlin_first(self, game):
        for seat in (ASSASSIN, MINION):
            merlin = game.memories[seat].merlin
            assert merlin.top() == MERLIN
            assert merlin.p_merlin[MERLIN] > 0.5
            assert sum(merlin.p_merlin.values()) == pytest.approx(1.0)

    def test_p0_is_already_top_before_any_evil_player_is_exposed(self):
        # Before Q3 fails, P0's accusations of P1 (#44) and P4 (#207, #239, #274, #320) were "early".
        game = replay_arena_game(EVENTS, TALK_EDGES, stop_after_seq=Q3_FAILED - 1)
        assert game.memories[ASSASSIN].merlin.top() == MERLIN

    def test_without_talk_edges_votes_alone_do_not_find_merlin(self):
        game = replay_arena_game(EVENTS)
        merlin = game.memories[ASSASSIN].merlin
        assert merlin.p_merlin[MERLIN] < 0.68


class TestVisualizer:
    def test_one_snapshot_per_step_per_player(self):
        data = build_data(EVENTS, TALK_EDGES, "game4")
        assert len(data["steps"]) == 102
        for seat, player in data["players"].items():
            assert len(player["snaps"]) == 102
            counts = [s["edgeCount"] for s in player["snaps"]]
            assert counts == sorted(counts)
        servant = data["players"]["2"]["snaps"]
        assert servant[-1]["beliefs"] == {"0": 0.0, "1": 1.0, "3": 0.0, "4": 1.0}
        assert not servant[-1]["consistent"]

    def test_html_embeds_the_data_safely(self):
        html = render_html(build_data(EVENTS, TALK_EDGES, "game4"))
        assert "__DATA__" not in html
        payload = html.split('<script id="data" type="application/json">')[1].split("</script>")[0]
        assert "</" not in payload


class TestPairBeliefContradictions:
    def test_pairs_that_fit_the_most_failed_quests_survive(self):
        beliefs = PairBelief(owner=2)
        beliefs.add_failed_quest([0, 2, 3], 1, {})
        beliefs.add_failed_quest([1, 4], 2, {})
        beliefs.add_failed_quest([1, 2, 4], 2, {})
        assert not beliefs.consistent
        assert beliefs.possible_pairs() == [(1, 4)]
        beliefs.set_rule()
        assert beliefs.p_evil == {0: 0.0, 1: 1.0, 3: 0.0, 4: 1.0}

    def test_an_unexplained_failed_quest_is_not_enforced_by_validate(self):
        beliefs = PairBelief(owner=2)
        beliefs.add_failed_quest([0, 2, 3], 1, {})
        beliefs.add_failed_quest([1, 4], 2, {})
        beliefs.add_failed_quest([1, 2, 4], 2, {})
        # P0 + P3 = 0 breaks the Q2 constraint, but no possible pair satisfies Q2 anyway.
        assert beliefs.validate({0: 0.0, 1: 1.0, 3: 0.0, 4: 1.0}) == []
