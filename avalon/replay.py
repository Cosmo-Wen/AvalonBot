"""
Reenacts a recorded Avalon-LLM arena game (`games/game_*.jsonl`) through AvalonBot.

Every event is delivered to each player's own PlayerMemory exactly as the runner would deliver it:
public events to everyone, quest cards only to the player who played them. The same events also
drive an AvalonEngine with the recorded roles and first leader, so any step the rules don't allow
(wrong leader, wrong team size, a good player playing Fail, ...) is reported as a violation.

Talk edges are not in the transcript. Pass hand-labelled ones (`talk_edges`) to stand in for each
player's extraction call; they are added after each discussion round, before the proposal.

Usage: py -3.12 -m avalon.replay <game.jsonl> [talk_edges.json] [--seat N]
"""

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from .belief_graph import brier_score
from .engine import AvalonEngine, Role
from .memory import PlayerMemory

ARENA_ROLES = {
    "Merlin": Role.MERLIN,
    "Servant": Role.LOYAL_SERVANT,
    "Assassin": Role.ASSASSIN,
    "Minion": Role.MINION,
}


@dataclass
class Replay:
    roles: Dict[int, Role]
    first_leader: int
    memories: Dict[int, PlayerMemory]
    violations: List[str] = field(default_factory=list)
    good_won: Optional[bool] = None
    # P(evil) each player reported at game end in the recorded game (arena logs P(good)).
    reported_p_evil: Dict[int, Dict[int, float]] = field(default_factory=dict)
    last_seq: int = 0

    @property
    def true_evil(self) -> List[int]:
        return sorted(p for p, role in self.roles.items() if role in (Role.ASSASSIN, Role.MINION))

    def rule_vs_reported_brier(self, seat: int) -> Dict[str, float]:
        """Brier score of this Servant's graph P(evil) and of the P(evil) it reported in the game."""
        beliefs = self.memories[seat].beliefs
        if beliefs is None or seat not in self.reported_p_evil:
            raise ValueError(f"Player {seat} has no P(evil) to compare")
        return {
            "graph": brier_score(dict(beliefs.p_evil), self.true_evil),
            "reported": brier_score(self.reported_p_evil[seat], self.true_evil),
        }


def load_events(path: str) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_talk_edges(path: str) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["edges"]


def replay_arena_game(
    events: Sequence[Dict[str, Any]],
    talk_edges: Iterable[Dict[str, Any]] = (),
    belief_mode: str = "rule",
    merlin_graph: bool = True,
    stop_after_seq: Optional[int] = None,
    on_step: Optional[Callable[[int, Dict[int, PlayerMemory]], None]] = None,
) -> Replay:
    """
    Feeds a recorded game into one PlayerMemory per seat. `stop_after_seq` replays only events with
    seq <= that value, to inspect a player's memory partway through the game. `on_step(seq, memories)`
    is called after every event that adds a log entry.
    """
    start = next(e for e in events if e["type"] == "game_start")["data"]
    roles = {s["seat"]: ARENA_ROLES[s["role"]] for s in start["seats"]}
    engine = AvalonEngine()
    engine.reset(preset_roles=roles, preset_leader=start["quest_leader"])
    memories = {
        seat: PlayerMemory(seat, engine.get_private_info(seat), belief_mode=belief_mode, merlin_graph=merlin_graph)
        for seat in roles
    }
    result = Replay(roles=roles, first_leader=start["quest_leader"], memories=memories)

    pending_edges = sorted(talk_edges, key=lambda raw: max(raw["sources"]))
    pending_votes: Optional[Dict[int, bool]] = None
    quest_round: Dict[int, int] = {}

    def deliver(event_type: str, data: Dict[str, Any]) -> None:
        for memory in memories.values():
            memory.observe(event_type, dict(data))

    def add_edges_up_to(seq: int) -> None:
        while pending_edges and max(pending_edges[0]["sources"]) <= seq:
            raw = pending_edges.pop(0)
            for memory in memories.values():
                _, dropped = memory.add_talk_edges([raw])
                if dropped:
                    raise ValueError(f"Talk edge {raw} does not cite utterances by player {raw['from']}")

    def check(step: str, call) -> Any:
        try:
            return call()
        except (ValueError, RuntimeError) as exc:
            result.violations.append(f"{step}: {exc}")
            return None

    for event in events:
        seq, kind, d = event["seq"], event["type"], event["data"]
        if stop_after_seq is not None and seq > stop_after_seq:
            break
        result.last_seq = seq

        if kind == "discussion":
            deliver("utterance", {
                "seq": seq, "turn": d["quest"], "round_num": d["round"],
                "speaker": d["seat"], "text": d["text"],
            })

        elif kind == "team_proposed":
            add_edges_up_to(seq)
            where = f"Q{d['quest'] + 1}.{d['round'] + 1} proposal"
            if (engine.turn, engine.round_num) != (d["quest"], d["round"]):
                result.violations.append(
                    f"{where}: engine is at Q{engine.turn + 1}.{engine.round_num + 1}"
                )
            check(where, lambda: engine.choose_team(d["leader"], d["team"]))
            deliver("team_proposed", {
                "seq": seq, "turn": d["quest"], "round_num": d["round"],
                "leader": d["leader"], "team": d["team"],
            })

        elif kind == "team_votes":
            pending_votes = {seat: bool(v) for seat, v in enumerate(d["votes"])}

        elif kind == "team_result":
            votes = pending_votes or {}
            where = f"Q{d['quest'] + 1}.{d['round'] + 1} team vote"
            outcome = check(where, lambda: engine.vote_on_team(votes))
            if outcome is not None and outcome[2] != d["approved"]:
                result.violations.append(f"{where}: recorded approved={d['approved']}, rules give {outcome[2]}")
            if d["approved"]:
                quest_round[d["quest"]] = d["round"]
            deliver("team_vote_result", {
                "seq": seq, "turn": d["quest"], "round_num": d["round"],
                "team": d["team"], "votes": votes, "approved": d["approved"],
            })
            pending_votes = None

        elif kind == "quest_votes":
            cards = {int(seat): bool(card) for seat, card in d["votes"].items()}
            quest = engine.turn
            for seat, passed in cards.items():
                memories[seat].record_quest_card(quest + 1, passed)
            illegal = [p for p, passed in cards.items() if not passed and engine.player_sides.get(p)]
            for p in illegal:
                result.violations.append(
                    f"Q{quest + 1} quest: Player {p} ({roles[p].name}) is good but played Fail"
                )
            # Count the illegal Fail as the game did, so the rest of the game can still be checked.
            sides = dict(engine.player_sides)
            engine.player_sides.update({p: False for p in illegal})
            check(f"Q{quest + 1} quest", lambda: engine.vote_on_quest(cards))
            engine.player_sides = sides

        elif kind == "quest_result":
            deliver("quest_result", {
                "seq": seq, "turn": d["quest"], "round_num": quest_round.get(d["quest"], 0),
                "team": d["team"], "success": d["succeeded"], "num_fails": d["num_fails"],
            })

        elif kind == "beliefs":
            result.reported_p_evil = {
                seat: {p: 1.0 - float(v) for p, v in enumerate(row) if p != seat}
                for seat, row in enumerate(d["believed"])
            }

        elif kind == "game_end":
            result.good_won = engine.good_victory if engine.game_over else None

        if on_step is not None and kind in ("discussion", "team_proposed", "team_result", "quest_result"):
            on_step(seq, memories)

    return result


def main(argv: Sequence[str]) -> None:
    args = list(argv)
    seat: Optional[int] = None
    if "--seat" in args:
        i = args.index("--seat")
        seat = int(args[i + 1])
        del args[i:i + 2]
    if not args:
        print(__doc__)
        return
    edges = load_talk_edges(args[1]) if len(args) > 1 else []
    replay = replay_arena_game(load_events(args[0]), edges)

    print(f"Roles: {', '.join(f'P{p} {r.name}' for p, r in sorted(replay.roles.items()))}")
    print(f"Violations: {replay.violations or 'none'}")
    for s, memory in sorted(replay.memories.items()):
        if seat is not None and s != seat:
            continue
        print(f"\n=== Player {s} ({replay.roles[s].name}) ===")
        print(memory.render_table())


if __name__ == "__main__":
    main(sys.argv[1:])
