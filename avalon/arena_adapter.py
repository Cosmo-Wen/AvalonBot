"""
Turns arena events into belief-graph edges.

Arena logs (`games/game_*.jsonl`, written by the vendored `arena` runner) record a game as events:
`discussion`, `team_proposed`, `team_votes` + `team_result`, `quest_votes` + `quest_result`, ...
`ArenaGraphAdapter` feeds those events, one at a time, into one `PlayerMemory` per seat: the same
memory and knowledge-graph module the live demo uses. Each player gets only what it would see in
play: public events go to everyone, a quest card only to the player who played it, and evil-only
chat only to the evil seats.

The same events also drive an `AvalonEngine` with the recorded roles and first leader, so any step
the rules don't allow (wrong leader, wrong team size, a good player playing Fail, ...) is recorded
as a violation.

It works live (feed each event as the game emits it) or offline over a finished log; see
`avalon.replay` for the offline command.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .belief_graph import brier_score
from .engine import AvalonEngine, Role, ROLE_SIDES
from .memory import PlayerMemory

ARENA_ROLES = {
    "Percival": Role.PERCIVAL,
    "Morgana": Role.MORGANA,
    "Merlin": Role.MERLIN,
    "Servant": Role.LOYAL_SERVANT,
    "Assassin": Role.ASSASSIN,
    "Minion": Role.MINION,
}

# events after which a player's memory has a new log entry
STEP_EVENTS = ("discussion", "team_proposed", "team_result", "quest_result")


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
        return sorted(p for p, role in self.roles.items() if not ROLE_SIDES[role])

    def rule_vs_reported_brier(self, seat: int) -> Dict[str, float]:
        """Brier score of this Servant's graph P(evil) and of the P(evil) it reported in the game."""
        beliefs = self.memories[seat].beliefs
        if beliefs is None or seat not in self.reported_p_evil:
            raise ValueError(f"Player {seat} has no P(evil) to compare")
        return {
            "graph": brier_score(dict(beliefs.p_evil), self.true_evil),
            "reported": brier_score(self.reported_p_evil[seat], self.true_evil),
        }


class ArenaGraphAdapter:
    r"""
    Feed arena events in order with `feed(event)`; read `state.memories` at any point.

    `talk_edges` (hand-labelled or extracted elsewhere) are added after the discussion they cite,
    before the next proposal: to the edge's `owner` only if it has one, otherwise to every player. Without them, memories hold every action edge and the raw talk,
    but no talk edges.
    """

    def __init__(self, talk_edges: Iterable[Dict[str, Any]] = (), belief_mode: str = "rule",
                 merlin_graph: bool = True):
        self.belief_mode = belief_mode
        self.merlin_graph = merlin_graph
        self.pending_edges = sorted(talk_edges, key=lambda raw: max(raw["sources"]))
        self.dropped_edges = 0  # owned (extracted) edges the player's memory rejected, as it did live
        self.pending_votes: Optional[Dict[int, bool]] = None
        self.quest_round: Dict[int, int] = {}
        self.engine: Optional[AvalonEngine] = None
        self.state: Optional[Replay] = None

    @property
    def memories(self) -> Dict[int, PlayerMemory]:
        return self.state.memories if self.state is not None else {}

    # delivery

    def _deliver(self, event_type: str, data: Dict[str, Any], seats: Optional[Iterable[int]] = None) -> None:
        for seat in (self.memories if seats is None else seats):
            self.memories[seat].observe(event_type, dict(data))

    def _add_edges_up_to(self, seq: int) -> None:
        while self.pending_edges and max(self.pending_edges[0]["sources"]) <= seq:
            raw = self.pending_edges.pop(0)
            # an edge with an "owner" came from that player's own extraction call; others go to everyone
            owners = [raw["owner"]] if raw.get("owner") is not None else list(self.memories)
            for owner in owners:
                _, dropped = self.memories[owner].add_talk_edges([raw])
                if dropped and raw.get("owner") is not None:
                    self.dropped_edges += dropped  # the live memory dropped it too
                elif dropped:
                    raise ValueError(f"Talk edge {raw} does not cite utterances by player {raw['from']}")

    def _check(self, step: str, call) -> Any:
        try:
            return call()
        except (ValueError, RuntimeError) as exc:
            self.state.violations.append(f"{step}: {exc}")
            return None

    # events

    def feed(self, event: Dict[str, Any]) -> bool:
        r"""Applies one arena event. Returns True when it added an entry to the players' logs."""
        seq, kind, d = event["seq"], event["type"], event["data"]
        if kind == "game_start":
            self._start(d)
            return False
        if self.state is None:
            raise ValueError(f"event {kind!r} (seq {seq}) before game_start")
        self.state.last_seq = seq
        engine, state = self.engine, self.state

        if kind == "discussion":
            self._deliver("utterance", {
                "seq": seq, "turn": d["quest"], "round_num": d["round"],
                "speaker": d["seat"], "text": d["text"],
            })

        elif kind == "evil_chat":
            evil = [p for p, role in state.roles.items() if not ROLE_SIDES[role]]
            self._deliver("evil_chat", {
                "seq": seq, "turn": d["quest"], "round_num": 0, "speaker": d["seat"], "text": d["text"],
            }, seats=evil)

        elif kind == "team_proposed":
            self._add_edges_up_to(seq)
            where = f"Q{d['quest'] + 1}.{d['round'] + 1} proposal"
            if (engine.turn, engine.round_num) != (d["quest"], d["round"]):
                state.violations.append(f"{where}: engine is at Q{engine.turn + 1}.{engine.round_num + 1}")
            self._check(where, lambda: engine.choose_team(d["leader"], d["team"]))
            self._deliver("team_proposed", {
                "seq": seq, "turn": d["quest"], "round_num": d["round"],
                "leader": d["leader"], "team": d["team"],
            })

        elif kind == "team_votes":
            self.pending_votes = {seat: bool(v) for seat, v in enumerate(d["votes"])}

        elif kind == "team_result":
            votes = self.pending_votes or {}
            where = f"Q{d['quest'] + 1}.{d['round'] + 1} team vote"
            outcome = self._check(where, lambda: engine.vote_on_team(votes))
            if outcome is not None and outcome[2] != d["approved"]:
                state.violations.append(f"{where}: recorded approved={d['approved']}, rules give {outcome[2]}")
            if d["approved"]:
                self.quest_round[d["quest"]] = d["round"]
            self._deliver("team_vote_result", {
                "seq": seq, "turn": d["quest"], "round_num": d["round"],
                "team": d["team"], "votes": votes, "approved": d["approved"],
            })
            self.pending_votes = None

        elif kind == "quest_votes":
            cards = {int(seat): bool(card) for seat, card in d["votes"].items()}
            quest = engine.turn
            for seat, passed in cards.items():
                self.memories[seat].record_quest_card(quest + 1, passed)
            illegal = [p for p, passed in cards.items() if not passed and engine.player_sides.get(p)]
            for p in illegal:
                state.violations.append(f"Q{quest + 1} quest: Player {p} ({state.roles[p].name}) is good but played Fail")
            # Count the illegal Fail as the game did, so the rest of the game can still be checked.
            sides = dict(engine.player_sides)
            engine.player_sides.update({p: False for p in illegal})
            self._check(f"Q{quest + 1} quest", lambda: engine.vote_on_quest(cards))
            engine.player_sides = sides

        elif kind == "quest_result":
            self._deliver("quest_result", {
                "seq": seq, "turn": d["quest"], "round_num": self.quest_round.get(d["quest"], 0),
                "team": d["team"], "success": d["succeeded"], "num_fails": d["num_fails"],
            })

        elif kind == "beliefs":
            state.reported_p_evil = {
                seat: {p: 1.0 - float(v) for p, v in enumerate(row) if p != seat}
                for seat, row in enumerate(d["believed"])
                if row is not None
            }

        elif kind == "game_end":
            state.good_won = engine.good_victory if engine.game_over else None

        return kind in STEP_EVENTS

    def _start(self, d: Dict[str, Any]) -> None:
        roles = {s["seat"]: ARENA_ROLES[s["role"]] for s in d["seats"]}
        self.engine = AvalonEngine()
        self.engine.reset(preset_roles=roles, preset_leader=d["quest_leader"])
        memories = {
            seat: PlayerMemory(seat, self.engine.get_private_info(seat), belief_mode=self.belief_mode,
                               merlin_graph=self.merlin_graph,
                               percival_condition=d.get("percival_condition", "chat_only"))
            for seat in roles
        }
        self.state = Replay(roles=roles, first_leader=d["quest_leader"], memories=memories)
