"""
Serializes each player's PlayerMemory (knowledge graph, beliefs, constraints) for the spectator UI.
"""

from typing import Any, Dict

from avalon.belief_graph import TALK_EDGES
from avalon.memory import PlayerMemory


def serialize_memory(memory: PlayerMemory) -> Dict[str, Any]:
    graph = memory.graph
    if memory.beliefs is not None:
        belief_name = "P(evil)"
        beliefs = {str(p): round(v, 4) for p, v in memory.beliefs.p_evil.items()}
        consistent = memory.beliefs.consistent
    elif memory.merlin is not None:
        belief_name = "P(Merlin)"
        beliefs = {str(p): round(v, 4) for p, v in memory.merlin.p_merlin.items()}
        consistent = True
    else:
        belief_name, beliefs, consistent = None, {}, True

    return {
        "owner": memory.owner,
        "role": memory.private.role_name,
        "side": "Good" if memory.private.side else "Evil",
        "seenEvil": list(memory.private.seen_evil),
        "beliefName": belief_name,
        "beliefs": beliefs,
        "consistent": consistent,
        "constraints": [line.replace("Constraints: ", "") for line in graph.render_constraints()],
        "cards": {str(q): passed for q, passed in memory.private.my_quest_cards.items()},
        "edges": [
            {"id": e.id, "type": e.type, "src": e.src, "dst": e.dst, "seq": e.seq,
             "quest": e.quest, "quote": e.quote, "sources": e.sources, "role": e.role}
            for e in graph.edges if e.type in TALK_EDGES
        ],
        "flags": [
            {"talk": t.id, "voteSeq": v.seq, "team": v.dst}
            for t, v in graph.contradictions()
        ],
        "teams": [
            {"label": t.label, "quest": t.quest, "attempt": t.attempt, "leader": t.leader,
             "members": list(t.members), "votes": {str(p): v for p, v in t.votes.items()},
             "approved": t.approved, "fails": t.fails, "success": t.success}
            for t in graph.teams.values()
        ],
        "notes": {str(p): n for p, n in memory.notes.items()},
        "logSize": len(memory.log),
    }


def serialize_memories(memories: Dict[int, PlayerMemory]) -> Dict[str, Any]:
    return {str(seat): serialize_memory(m) for seat, m in sorted(memories.items())}
