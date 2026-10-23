"""Unit tests for the 5-Player Avalon rules engine."""

import unittest
from avalon.engine import AvalonEngine, Role, Phase


class TestAvalonEngine(unittest.TestCase):
    def setUp(self):
        self.engine = AvalonEngine(seed=42)
        self.engine.reset()

    def test_role_distribution(self):
        roles = list(self.engine.player_roles.values())
        self.assertEqual(roles.count(Role.MERLIN), 1)
        self.assertEqual(roles.count(Role.LOYAL_SERVANT), 2)
        self.assertEqual(roles.count(Role.MINION), 1)
        self.assertEqual(roles.count(Role.ASSASSIN), 1)

        sides = list(self.engine.player_sides.values())
        self.assertEqual(sides.count(True), 3)   # 3 Good
        self.assertEqual(sides.count(False), 2)  # 2 Evil

    def test_private_info(self):
        merlin = self.engine.get_merlin()
        assassin = self.engine.get_assassin()
        evil_players = self.engine.get_evil_players()
        servants = [p for p, r in self.engine.player_roles.items() if r == Role.LOYAL_SERVANT]

        # Merlin sees both evil players
        merlin_info = self.engine.get_private_info(merlin)
        self.assertEqual(sorted(merlin_info["seen_evil"]), sorted(evil_players))

        # Assassin sees other evil player (the minion)
        assassin_info = self.engine.get_private_info(assassin)
        other_evil = [p for p in evil_players if p != assassin]
        self.assertEqual(assassin_info["seen_evil"], other_evil)

        # Servant sees no one
        servant_info = self.engine.get_private_info(servants[0])
        self.assertEqual(servant_info["seen_evil"], [])

    def test_team_proposals_and_hammer(self):
        # Quest 0 requires 2 players
        leader = self.engine.leader
        self.engine.choose_team(leader, [0, 1])
        self.assertEqual(self.engine.phase, Phase.TEAM_VOTING)

        # Reject vote (all vote False)
        phase, game_over, approved = self.engine.vote_on_team({i: False for i in range(5)})
        self.assertFalse(approved)
        self.assertEqual(self.engine.round_num, 1)
        self.assertEqual(self.engine.phase, Phase.TEAM_SELECTION)

        # Repeat rejections until round 4 (the 5th round / hammer)
        for _ in range(3):
            self.engine.choose_team(self.engine.leader, [0, 1])
            self.engine.vote_on_team({i: False for i in range(5)})

        self.assertEqual(self.engine.round_num, 4)
        self.engine.choose_team(self.engine.leader, [0, 1])
        # Even if all reject on round 4, hammer auto-passes
        phase, game_over, approved = self.engine.vote_on_team({i: False for i in range(5)})
        self.assertTrue(approved)
        self.assertEqual(self.engine.phase, Phase.QUEST_VOTING)

    def test_good_cannot_fail_quest(self):
        merlin = self.engine.get_merlin()
        servants = [p for p, r in self.engine.player_roles.items() if r == Role.LOYAL_SERVANT]
        team = [merlin, servants[0]]

        self.engine.choose_team(self.engine.leader, team)
        self.engine.vote_on_team({i: True for i in range(5)})

        with self.assertRaises(ValueError):
            # Good player voting False must raise ValueError
            self.engine.vote_on_quest({merlin: False, servants[0]: True})

    def test_evil_wins_by_three_failed_quests(self):
        # 3 quests fail
        evil_players = self.engine.get_evil_players()

        for q in range(3):
            req_size = self.engine.get_required_team_size()
            team = [evil_players[0]] + list(range(req_size - 1))
            team = sorted(list(set(team)))
            while len(team) < req_size:
                for p in range(5):
                    if p not in team:
                        team.append(p)
                        break

            self.engine.choose_team(self.engine.leader, team)
            self.engine.vote_on_team({i: True for i in range(5)})

            # Evil fails quest
            quest_votes = {}
            for p in team:
                if p == evil_players[0]:
                    quest_votes[p] = False  # Fail
                else:
                    quest_votes[p] = True   # Pass

            self.engine.vote_on_quest(quest_votes)

        self.assertTrue(self.engine.game_over)
        self.assertFalse(self.engine.good_victory)
        self.assertEqual(self.engine.phase, Phase.GAME_OVER)

    def test_good_wins_merlin_survives(self):
        # Presetting roles to test deterministically
        preset_roles = {
            0: Role.MERLIN,
            1: Role.LOYAL_SERVANT,
            2: Role.LOYAL_SERVANT,
            3: Role.MINION,
            4: Role.ASSASSIN,
        }
        self.engine.reset(preset_roles=preset_roles, preset_leader=0)

        # 3 consecutive successful quests with pure good teams
        good_players = [0, 1, 2]

        for q in range(3):
            req_size = self.engine.get_required_team_size()
            team = good_players[:req_size]

            self.engine.choose_team(self.engine.leader, team)
            self.engine.vote_on_team({i: True for i in range(5)})
            self.engine.vote_on_quest({p: True for p in team})

        # Must be in ASSASSINATION phase
        self.assertEqual(self.engine.phase, Phase.ASSASSINATION)
        self.assertFalse(self.engine.game_over)

        # Assassin guesses wrong (guesses Player 1, not Merlin 0)
        phase, game_over, good_victory = self.engine.assassinate(assassin=4, target=1)
        self.assertTrue(game_over)
        self.assertTrue(good_victory)
        self.assertEqual(phase, Phase.GAME_OVER)

    def test_evil_wins_by_assassination(self):
        preset_roles = {
            0: Role.MERLIN,
            1: Role.LOYAL_SERVANT,
            2: Role.LOYAL_SERVANT,
            3: Role.MINION,
            4: Role.ASSASSIN,
        }
        self.engine.reset(preset_roles=preset_roles, preset_leader=0)

        good_players = [0, 1, 2]
        for q in range(3):
            req_size = self.engine.get_required_team_size()
            team = good_players[:req_size]

            self.engine.choose_team(self.engine.leader, team)
            self.engine.vote_on_team({i: True for i in range(5)})
            self.engine.vote_on_quest({p: True for p in team})

        # Assassin hits Merlin (Player 0)
        phase, game_over, good_victory = self.engine.assassinate(assassin=4, target=0)
        self.assertTrue(game_over)
        self.assertFalse(good_victory)

    def test_instances_do_not_share_state(self):
        engine1 = AvalonEngine(seed=1)
        engine2 = AvalonEngine(seed=2)
        engine1.reset()
        engine2.reset()

        # Mutate engine1
        engine1.choose_team(engine1.leader, [0, 1])
        # engine2 must remain unaffected
        self.assertEqual(engine1.phase, Phase.TEAM_VOTING)
        self.assertEqual(engine2.phase, Phase.TEAM_SELECTION)
        self.assertEqual(len(engine2.current_team), 0)


if __name__ == "__main__":
    unittest.main()
