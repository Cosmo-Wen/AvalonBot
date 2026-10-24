"""
Tool Definitions and Dispatcher for Avalon LLM Agents.

Implements the official tool-calling schema (compatible with both
Boson ChatCompletions and Boson Higgs Realtime API).

Game actions:
- propose_team(team, reasoning)
- vote_on_team(approve, reason)
- vote_on_quest(pass_quest)
- assassinate(target, reason)

Memory (see MEMORY_MODEL.md):
- record_observations(edges, p_evil, notes): a player's own extraction call
- report_beliefs(p_evil): final P(evil) in condition A
- recall / quote / evidence / my_record: exact lookup over the caller's own memory
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
]

_P_EVIL_SCHEMA = {
    "type": "object",
    "description": (
        "Probability each other player is evil, keyed by player id. Exactly 2 of your 4 opponents are evil, "
        "so the values must sum to 2. Each failed team's members must sum to at least its number of fails."
    ),
    "additionalProperties": {"type": "number"},
}

MEMORY_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "record_observations",
            "description": "Record what you heard in this discussion round into your private memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "edges": {
                        "type": "array",
                        "description": "Talk evidence from this round. Each edge must cite the seq numbers of the speaker's own lines.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": ["accused", "defended", "backed_team", "opposed_team", "claimed_role"],
                                },
                                "from": {"type": "integer", "description": "The speaker."},
                                "to": {
                                    "description": "A player id for accused/defended, or a team label like Q2.1 for backed_team/opposed_team.",
                                },
                                "role": {"type": "string", "description": "For claimed_role: the role claimed."},
                                "sources": {"type": "array", "items": {"type": "integer"}, "description": "Log seq numbers of the speaker's lines."},
                                "quote": {"type": "string", "description": "At most 10 words from the source line."},
                            },
                            "required": ["type", "from", "sources"],
                        },
                    },
                    "p_evil": _P_EVIL_SCHEMA,
                    "notes": {
                        "type": "object",
                        "description": "At most 15 words per player, keyed by player id.",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["edges", "notes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_beliefs",
            "description": "Report how likely each other player is to be evil.",
            "parameters": {
                "type": "object",
                "properties": {"p_evil": _P_EVIL_SCHEMA},
                "required": ["p_evil"],
            },
        },
    },
]

RECALL_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": "Look up entries in your own observation log. All filters are optional.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player": {"type": "integer", "description": "Only entries involving this player."},
                    "from_seq": {"type": "integer"},
                    "to_seq": {"type": "integer"},
                    "kinds": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["utterance", "proposal", "team_vote", "quest_result", "evil_chat"]},
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "quote",
            "description": "Get the full text of one entry in your log.",
            "parameters": {
                "type": "object",
                "properties": {"seq": {"type": "integer"}},
                "required": ["seq"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evidence",
            "description": "All evidence in your memory about one player, with the entries it came from.",
            "parameters": {
                "type": "object",
                "properties": {"player": {"type": "integer"}},
                "required": ["player"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "my_record",
            "description": "What you said, why you voted and proposed as you did, and your quest cards.",
            "parameters": {
                "type": "object",
                "properties": {"quest": {"type": "integer", "description": "Optional quest number, counted from 1."}},
            },
        },
    },
]

RECALL_TOOL_NAMES = {t["function"]["name"] for t in RECALL_TOOL_DEFINITIONS}

ALL_TOOL_DEFINITIONS = AVALON_TOOL_DEFINITIONS + MEMORY_TOOL_DEFINITIONS + RECALL_TOOL_DEFINITIONS


def get_tool(name: str) -> Dict[str, Any]:
    for tool in ALL_TOOL_DEFINITIONS:
        if tool["function"]["name"] == name:
            return tool
    raise KeyError(f"Unknown tool {name}")


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
