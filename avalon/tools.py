"""
Tool Definitions and Dispatcher for Avalon LLM Agents.

Implements the official tool-calling schema (compatible with both
Boson ChatCompletions and Boson Higgs Realtime API).

Tools represent the official game actions:
- propose_team(team: List[int])
- vote_on_team(approve: bool, reason: str)
- vote_on_quest(pass_quest: bool)
- assassinate(target: int)
- update_belief_graph(player_id: int, p_evil: float, reason: str)
"""

from typing import Dict, List, Any, Optional
import json


# Standard JSON Schemas for tools
AVALON_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "propose_team",
            "description": "Propose a team of players for the current quest as the Quest Leader. Call this when it is your turn to propose a team.",
            "parameters": {
                "type": "object",
                "properties": {
                    "team": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "The exact list of player IDs (e.g. [0, 1]) to go on the mission.",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Why you chose this specific combination of players.",
                    },
                },
                "required": ["team"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vote_on_team",
            "description": "Vote to approve or reject the proposed quest team. Call this during the team voting phase.",
            "parameters": {
                "type": "object",
                "properties": {
                    "approve": {
                        "type": "boolean",
                        "description": "True to approve the proposed team, False to reject it.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Short justification for your vote.",
                    },
                },
                "required": ["approve"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vote_on_quest",
            "description": "Cast a secret vote on the quest as a team member. Good players must vote pass; Evil players may vote pass (to bluff) or fail (to score for Evil).",
            "parameters": {
                "type": "object",
                "properties": {
                    "pass_quest": {
                        "type": "boolean",
                        "description": "True to vote Pass/Success, False to vote Fail.",
                    },
                },
                "required": ["pass_quest"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assassinate",
            "description": "As the Assassin, guess and assassinate Merlin after Good successfully passes 3 quests.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "integer",
                        "description": "The player ID of the suspected Merlin.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why you believe this player is Merlin.",
                    },
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_belief",
            "description": "Update your structured belief graph regarding suspicion of other players.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player": {
                        "type": "integer",
                        "description": "The player ID being evaluated.",
                    },
                    "p_evil": {
                        "type": "number",
                        "description": "Probability that this player is Evil (between 0.0 and 1.0).",
                    },
                    "evidence": {
                        "type": "string",
                        "description": "Key observations or voting patterns justifying this belief.",
                    },
                },
                "required": ["player", "p_evil"],
            },
        },
    },
]


def format_tools_for_realtime() -> List[Dict[str, Any]]:
    """
    Higgs Realtime WebSocket format expects:
    [{"type": "function", "name": "...", "description": "...", "parameters": {...}}]
    (unwrapped without the inner 'function' key).
    """
    realtime_tools = []
    for tool in AVALON_TOOL_DEFINITIONS:
        fn = tool["function"]
        realtime_tools.append({
            "type": "function",
            "name": fn["name"],
            "description": fn["description"],
            "parameters": fn["parameters"],
        })
    return realtime_tools


def format_tools_for_chat_completions() -> List[Dict[str, Any]]:
    """
    Standard OpenAI / Boson Chat Completions format with 'function' envelope.
    """
    return AVALON_TOOL_DEFINITIONS
