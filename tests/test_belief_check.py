"""Condition B's P(evil) must use the failed-quest evidence: re-ask once, then fall back to the pair rule."""

import asyncio
import unittest

from test_memory import Feed, stub_servant

# P0 is a Loyal Servant. Q1 team {1, 3} failed with 1 fail (P1 and P3 are in fact the evil pair).
UNIFORM = {"edges": [], "notes": {}, "p_evil": {"1": 0.5, "2": 0.5, "3": 0.5, "4": 0.5}}
INFORMED = {"edges": [], "notes": {}, "p_evil": {"1": 0.7, "2": 0.3, "3": 0.7, "4": 0.3}}
# valid under the coherence rules (sums to 2; P1 + P3 >= 1), but P3 ranks below P2
WRONG_TOP = {"edges": [], "notes": {}, "p_evil": {"1": 0.9, "2": 0.6, "3": 0.3, "4": 0.2}}


def after_failed_quest(answers):
    agent = stub_servant([])
    feed = Feed(agent.memory)
    feed.team(0, 0, 1, [1, 3], {0: True, 1: True, 2: False, 3: True, 4: False})
    feed.quest(0, 0, [1, 3], fails=1)
    feed.say(1, 0, 4, "Let's think about who was on that quest.")
    agent.answers = list(answers)
    asyncio.run(agent.after_discussion(1, 0))
    return agent


class TestBeliefEvidenceCheck(unittest.TestCase):
    def test_informed_beliefs_are_accepted_first_time(self):
        agent = after_failed_quest([INFORMED])
        self.assertEqual(agent.memory.beliefs.source, "llm")
        self.assertEqual(agent.memory.belief_paths, {"llm": 1})
        self.assertEqual(len(agent.prompts), 1)

    def test_all_half_is_rejected_and_re_asked(self):
        agent = after_failed_quest([UNIFORM, INFORMED])
        self.assertIn("all values are 0.5", agent.prompts[1])
        self.assertEqual(agent.memory.beliefs.source, "llm")
        self.assertAlmostEqual(agent.memory.beliefs.p_evil[3], 0.7)
        self.assertEqual(agent.memory.belief_paths, {"llm_retry": 1})

    def test_failed_team_must_be_the_top_suspects(self):
        agent = after_failed_quest([WRONG_TOP, INFORMED])
        self.assertIn("P1, P3 were on a failed quest, so they must be your top suspects", agent.prompts[1])
        self.assertEqual(agent.memory.belief_paths, {"llm_retry": 1})

    def test_two_bad_answers_fall_back_to_the_pair_rule(self):
        agent = after_failed_quest([UNIFORM, WRONG_TOP])
        beliefs = agent.memory.beliefs
        self.assertEqual(beliefs.source, "rule")
        self.assertEqual(agent.memory.belief_paths, {"rule_fallback": 1})
        self.assertEqual(agent.memory.belief_fallbacks, 1)
        self.assertEqual(beliefs.p_evil, beliefs.rule_marginals())
        self.assertGreater(min(beliefs.p_evil[1], beliefs.p_evil[3]), max(beliefs.p_evil[2], beliefs.p_evil[4]))

    def test_half_is_fine_before_any_evidence(self):
        agent = stub_servant([])
        Feed(agent.memory).say(0, 0, 4, "No quests yet, so I have no read.")
        agent.answers = [UNIFORM]
        asyncio.run(agent.after_discussion(0, 0))
        self.assertEqual(agent.memory.belief_paths, {"llm": 1})
        self.assertEqual(len(agent.prompts), 1)

    def test_uninformative_team_is_not_enforced(self):
        # team {1, 2, 3} with 1 fail: every pair of P0's opponents {1, 2, 3, 4} contains one of them,
        # so the quest rules out no pair, and 0.5 for everyone is still the right answer
        agent = stub_servant([])
        feed = Feed(agent.memory)
        feed.team(0, 0, 1, [1, 2, 3], {p: True for p in range(5)})
        feed.quest(0, 0, [1, 2, 3], fails=1)
        beliefs = agent.memory.beliefs
        self.assertEqual(set(beliefs.counting_marginals().values()), {0.5})
        self.assertEqual(beliefs.evidence_errors({1: 0.5, 2: 0.5, 3: 0.5, 4: 0.5}), [])


if __name__ == "__main__":
    unittest.main()
