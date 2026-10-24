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
