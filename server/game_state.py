"""
Serialization helpers for the Avalon spectator frontend WebSocket.

Converts AvalonEngine state, game events, and PlayerMemory snapshots into
JSON-friendly dicts the React frontend can render directly.
"""

import sys
import os
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from avalon.engine import AvalonEngine, Phase, PHASE_NAMES, Role, ROLE_NAMES  # noqa: E402

PLAYER_NAMES = {
    0: "Sir Galahad",
    1: "Sir Percival",
    2: "Sir Tristan",
    3: "Sir Mordred",
    4: "Lady Morgana",
}


def serialize_phase(phase: Phase) -> str:
    return PHASE_NAMES[phase].lower().replace(" ", "_")


def serialize_player(
    seat: int,
    engine: AvalonEngine,
    reveal_roles: bool = False,
    speaking_seat: int = -1,
) -> Dict[str, Any]:
    role = engine.player_roles.get(seat)
    side = engine.player_sides.get(seat)
    return {
        "seat": seat,
        "name": PLAYER_NAMES.get(seat, f"Player {seat}"),
        "role": ROLE_NAMES[role] if reveal_roles and role is not None else "Hidden",
        "side": ("Good" if side else "Evil") if reveal_roles and side is not None else "Hidden",
        "is_speaking": seat == speaking_seat,
        "is_leader": seat == engine.leader,
    }


def serialize_game_state(
    engine: AvalonEngine,
    reveal_roles: bool = False,
    speaking_seat: int = -1,
) -> Dict[str, Any]:
    good_wins = sum(1 for r in engine.quest_results if r)
    evil_wins = sum(1 for r in engine.quest_results if not r)
    return {
        "type": "game_state",
        "data": {
            "phase": serialize_phase(engine.phase),
            "turn": engine.turn,
            "round_num": engine.round_num,
            "leader": engine.leader,
            "quest_results": [
                {"quest": i + 1, "success": r} for i, r in enumerate(engine.quest_results)
            ],
            "scores": {"good": good_wins, "evil": evil_wins},
            "players": [
                serialize_player(s, engine, reveal_roles, speaking_seat)
                for s in range(engine.NUM_PLAYERS)
            ],
            "current_team": list(engine.current_team),
            "game_over": engine.game_over,
            "good_victory": engine.good_victory,
            "win_reason": engine.win_reason,
        },
    }


def serialize_event(
    event_type: str,
    data: Dict[str, Any],
    seq: int,
) -> Dict[str, Any]:
    msg: Dict[str, Any] = {
        "type": event_type,
        "seq": seq,
        "data": data,
    }
    return msg


# Arena JSONL event → frontend event translation.
# Arena logs use slightly different field names; this normalizes them.

def translate_arena_event(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Translates one arena JSONL event dict into the frontend WebSocket format.
    Returns None for events the frontend doesn't need."""
    kind = raw["type"]
    seq = raw["seq"]
    d = raw.get("data", {})

    if kind == "game_start":
        seats = d.get("seats", [])
        return serialize_event("game_start", {
            "players": [
                {
                    "seat": s["seat"],
                    "name": PLAYER_NAMES.get(s["seat"], f"Player {s['seat']}"),
                    "role": s.get("role", "Hidden"),
                    "side": "Evil" if s.get("role") in ("Assassin", "Minion") else "Good",
                }
                for s in seats
            ],
            "quest_leader": d.get("quest_leader", 0),
        }, seq)

    if kind == "discussion":
        return serialize_event("utterance", {
            "turn": d.get("quest", 0),
            "round_num": d.get("round", 0),
            "speaker": d.get("seat", 0),
            "text": d.get("text", ""),
        }, seq)

    if kind == "evil_chat":
        return serialize_event("evil_chat", {
            "turn": d.get("quest", 0),
            "round_num": 0,
            "speaker": d.get("seat", 0),
            "text": d.get("text", ""),
        }, seq)

    if kind == "team_proposed":
        return serialize_event("team_proposed", {
            "turn": d.get("quest", 0),
            "round_num": d.get("round", 0),
            "leader": d.get("leader", 0),
            "team": d.get("team", []),
        }, seq)

    if kind == "team_votes":
        return serialize_event("team_votes", {
            "turn": d.get("quest", 0),
            "round_num": d.get("round", 0),
            "votes": {i: bool(v) for i, v in enumerate(d.get("votes", []))},
        }, seq)

    if kind == "team_result":
        return serialize_event("team_vote_result", {
            "turn": d.get("quest", 0),
            "round_num": d.get("round", 0),
            "team": d.get("team", []),
            "approved": d.get("approved", False),
            "votes": {i: bool(v) for i, v in enumerate(d.get("votes", []))} if "votes" in d else {},
        }, seq)

    if kind == "quest_result":
        return serialize_event("quest_result", {
            "turn": d.get("quest", 0),
            "round_num": d.get("round", 0),
            "team": d.get("team", []),
            "success": d.get("succeeded", True),
            "num_fails": d.get("num_fails", 0),
        }, seq)

    if kind == "beliefs":
        believed = d.get("believed", [])
        return serialize_event("belief_update", {
            "beliefs": {
                seat: {p: round(1.0 - float(v), 4) for p, v in enumerate(row) if p != seat}
                for seat, row in enumerate(believed)
                if row is not None
            },
        }, seq)

    if kind == "game_end":
        return serialize_event("game_over", {
            "status": d.get("status", "completed"),
            "winner": d.get("winner", ""),
            "reason": d.get("reason", ""),
            "good_victory": d.get("winner") == "Good",
        }, seq)

    return None
