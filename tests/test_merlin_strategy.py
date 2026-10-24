from avalon.engine import Role
from avalon.llm_agent import MERLIN_HIDDEN_RULES, LLMAgent


def prompt(role, strategy):
    agent = LLMAgent(player_id=0, role=role, condition="rule_graph", api_key="test", merlin_strategy=strategy)
    agent.private_info = {"seen_evil": [1, 2]} if role == Role.MERLIN else {}
    return agent._build_system_prompt()


def test_hidden_rules_reach_merlin_only():
    assert MERLIN_HIDDEN_RULES in prompt(Role.MERLIN, "hidden")
    assert MERLIN_HIDDEN_RULES not in prompt(Role.MERLIN, "default")
    assert MERLIN_HIDDEN_RULES not in prompt(Role.LOYAL_SERVANT, "hidden")
    assert MERLIN_HIDDEN_RULES not in prompt(Role.ASSASSIN, "hidden")


def cover_merlin(seen_evil=(1, 2)):
    agent = LLMAgent(player_id=0, role=Role.MERLIN, condition="rule_graph", api_key="test",
                     merlin_strategy="cover", seed=1)
    agent.set_private_info({"role": Role.MERLIN, "side": True, "seen_evil": list(seen_evil)})
    agent._seq = 0

    def send(event_type, **data):
        agent._seq += 1
        agent.memory.observe(event_type, dict(data, seq=agent._seq))
    return agent, send


def failed_quest(send, team, turn=0):
    send("team_proposed", turn=turn, round_num=0, leader=team[0], team=team)
    send("team_vote_result", turn=turn, round_num=0, leader=team[0], team=team,
         votes={p: True for p in range(5)}, approved=True)
    send("quest_result", turn=turn, round_num=0, team=team, success=False, num_fails=1)


def test_cover_votes_like_a_servant_without_evidence():
    import asyncio
    agent, _ = cover_merlin()
    # with no failed quest, a clean team without Merlin looks no better than any other: reject,
    # though Merlin knows it is clean; a team with evil that includes Merlin: approve (cover)
    assert asyncio.run(agent.vote_on_team(0, 0, 3, [3, 4])) is False
    assert asyncio.run(agent.vote_on_team(0, 0, 3, [0, 1])) is True
    assert MERLIN_HIDDEN_RULES in agent._build_system_prompt()


def test_cover_overrides_only_at_match_point():
    import asyncio
    agent, send = cover_merlin()
    failed_quest(send, [0, 2])  # evil's first fail: public evidence now points at P2
    # P1 is evil but publicly unsuspected; a team with P1 and Merlin looks clean, but evil already has
    # a fail, so passing it gives evil a second: real knowledge overrides
    assert asyncio.run(agent.vote_on_team(1, 0, 3, [0, 1, 3])) is False
    assert asyncio.run(agent.vote_on_team(1, 0, 3, [0, 3, 4])) is True


def test_cover_proposal_includes_merlin_and_avoids_evil_at_match_point():
    import asyncio
    agent, send = cover_merlin()
    team = asyncio.run(agent.propose_team(0, 2))
    assert 0 in team and len(team) == 2
    failed_quest(send, [0, 2])
    for _ in range(10):
        team = asyncio.run(agent.propose_team(1, 3))
        assert 0 in team and not set(team) & {1, 2}
