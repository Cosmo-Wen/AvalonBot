"""
Agent interfaces and implementations for 5-Player Avalon.

Includes:
- Agent base class
- HeuristicAgent (fast rule-based baseline for ablation testing)
- LLMAgent (Condition A: chat history only; Condition B: chat history + belief graph)
- HumanAgent (interface for voice/web UI human participant)
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Set, Any
import random
import json
import re

from .engine import Role, Phase, ROLE_NAMES, ROLE_SIDES
from .memory import PlayerMemory


GRAPH_CONDITIONS = ("belief_graph", "rule_graph")

_ACCUSE_WORDS = ("not on this mission", "suspicious", "traitor", "trap", "keep player", "do not let", "don't trust", "sabotage", "deflecting", "filthy", "ignoring")
_DEFEND_WORDS = ("trust player", "safer choice", "far safer", "is fine", "innocent")
_PLAYER_REF = re.compile(r"player\s+(\d)", re.IGNORECASE)


class Agent(ABC):
    """
    Abstract Base Class for an Avalon Player.
    """

    def __init__(
        self,
        player_id: int,
        role: Role,
        num_players: int = 5,
        condition: str = "chat_only",  # "chat_only" (A), "belief_graph" (B), "rule_graph" (C)
        seed: Optional[int] = None,
        merlin_graph: bool = False,  # Demo only: evil keeps P(Merlin). Keep off in the ablation.
    ):
        self.merlin_graph = merlin_graph
        self.player_id = player_id
        self.role = role
        self.side = ROLE_SIDES[role]
        self.num_players = num_players
        self.condition = condition
        self.rng = random.Random(seed)

        self.private_info: Dict[str, Any] = {}
        self.memory: Optional[PlayerMemory] = None

    # Set True by agents whose P(evil) comes from an LLM call in condition B.
    llm_beliefs: bool = False

    @property
    def uses_graph(self) -> bool:
        return self.condition in GRAPH_CONDITIONS

    @property
    def is_servant(self) -> bool:
        return self.role == Role.LOYAL_SERVANT

    def set_private_info(self, info: Dict[str, Any]):
        """Starts a fresh private memory for a new game."""
        self.private_info = info
        self.role = info["role"]
        self.side = bool(info["side"])
        belief_mode = "llm" if (self.llm_beliefs and self.condition == "belief_graph") else "rule"
        self.memory = PlayerMemory(
            self.player_id, info, self.num_players,
            belief_mode=belief_mode,
            merlin_graph=self.merlin_graph,
        )

    @property
    def reads_talk(self) -> bool:
        """Whether this player turns discussion into talk edges in its own graph."""
        return (self.is_servant and self.uses_graph) or (not self.side and self.merlin_graph)

    def merlin_guess(self) -> Optional[int]:
        """The good player this evil player most suspects of being Merlin, if it keeps P(Merlin)."""
        if self.memory is None or self.memory.merlin is None:
            return None
        return self.memory.merlin.top()

    def observe_event(self, event_type: str, data: Dict[str, Any]):
        """Delivers a game event into this player's own observation log."""
        if self.memory is not None:
            self.memory.observe(event_type, data)

    def record_own_quest_card(self, turn: int, passed: bool):
        if self.memory is not None:
            self.memory.record_quest_card(turn + 1, passed)

    def _current_round_num(self) -> int:
        """Engine round_num of the current proposal, from this player's own log."""
        if self.memory is None or not self.memory.log:
            return 0
        return self.memory.log[-1].attempt - 1

    def _record_reason(self, turn: int, round_num: int, action: str, reason: str):
        if self.memory is not None:
            self.memory.record_reason(turn + 1, round_num + 1, action, reason)

    def suspicion(self, player: int) -> Optional[float]:
        """
        This player's own estimate that `player` is evil, or None if it has none.
        Servants use their graph only in conditions B and C.
        """
        seen_evil = self.private_info.get("seen_evil", [])
        if self.role == Role.MERLIN:
            return 1.0 if player in seen_evil else 0.0
        if self.memory is not None and self.memory.beliefs is not None and self.uses_graph:
            return self.memory.beliefs.get(player)
        return None

    async def after_discussion(self, turn: int, round_num: int) -> None:
        """Called after each discussion round, before the proposal. Own reasoning only."""
        return None

    async def evil_discussion(self, turn: int) -> str:
        """Evil-only talk before the assassination. Only the evil partner hears it."""
        return ""

    async def final_beliefs(self) -> Optional[Dict[int, float]]:
        """P(evil) at game end, for metrics. Only Loyal Servants report one."""
        if self.memory is None or self.memory.beliefs is None:
            return None
        return dict(self.memory.beliefs.p_evil)

    @abstractmethod
    async def team_discussion(
        self,
        turn: int,
        round_num: int,
        leader: int,
        team_size: int,
    ) -> str:
        """Produce a spoken discussion statement."""
        pass

    @abstractmethod
    async def propose_team(self, turn: int, team_size: int) -> List[int]:
        """Leader proposes a team of size team_size."""
        pass

    @abstractmethod
    async def vote_on_team(
        self,
        turn: int,
        round_num: int,
        leader: int,
        team: List[int],
    ) -> bool:
        """Vote Approve (True) or Reject (False) on proposed team."""
        pass

    @abstractmethod
    async def vote_on_quest(self, turn: int, team: List[int]) -> bool:
        """Cast secret quest vote. True = Pass, False = Fail."""
        pass

    @abstractmethod
    async def assassinate(self) -> int:
        """Assassin chooses a player to assassinate."""
        pass


class HeuristicAgent(Agent):
    """
    Fast rule-based agent for validation and ablation baselines.
    """

    def _others_by_suspicion(self) -> List[int]:
        """Other players, most suspicious first. Random order when this player has no estimate."""
        others = [p for p in range(self.num_players) if p != self.player_id]
        self.rng.shuffle(others)
        if all(self.suspicion(p) is None for p in others):
            return others
        return sorted(others, key=lambda p: -(self.suspicion(p) or 0.0))

    async def after_discussion(self, turn: int, round_num: int) -> None:
        """Reads the round's talk into this player's own graph with keyword rules."""
        if not (self.reads_talk and self.memory is not None):
            return
        edges = []
        for entry in self.memory.discussion_entries(turn + 1, round_num + 1):
            if entry.speaker == self.player_id:
                continue
            lowered = entry.text.lower()
            targets = {int(m) for m in _PLAYER_REF.findall(entry.text)} - {entry.speaker}
            if not targets:
                continue
            if any(w in lowered for w in _ACCUSE_WORDS):
                kind = "accused"
            elif any(w in lowered for w in _DEFEND_WORDS):
                kind = "defended"
            else:
                continue
            for target in sorted(targets):
                edges.append({"type": kind, "from": entry.speaker, "to": target, "sources": [entry.seq], "quote": entry.text})
        self.memory.add_talk_edges(edges)

    async def evil_discussion(self, turn: int) -> str:
        guess = self.merlin_guess()
        if guess is not None:
            return f"Player {guess} has been too accurate all game. That's our Merlin."
        seen_evil = self.private_info.get("seen_evil", [])
        good = [p for p in range(self.num_players) if p not in seen_evil and p != self.player_id]
        return f"My guess for Merlin is Player {self.rng.choice(good)}." if good else ""

    async def team_discussion(self, turn: int, round_num: int, leader: int, team_size: int) -> str:
        if self.player_id == leader:
            return f"As leader for Quest {turn + 1}, I will propose a trustworthy team of size {team_size}."
        if self.side:
            top_suspect = self._others_by_suspicion()[0]
            if self.suspicion(top_suspect) is not None:
                return f"I want to make sure Player {top_suspect} is not on this mission."
            return f"I support building a clean good team for Quest {turn + 1}."
        else:
            return f"I am a loyal servant of Arthur. Put me on the quest team."

    async def propose_team(self, turn: int, team_size: int) -> List[int]:
        team = [self.player_id]

        if self.side:
            # Good: pick least suspicious players
            safest_first = list(reversed(self._others_by_suspicion()))
            team.extend(safest_first[: team_size - 1])
            reason = "picked the players I suspect least"
        else:
            # Evil: leader includes self and blends in with random others
            others = [p for p in range(self.num_players) if p != self.player_id]
            self.rng.shuffle(others)
            team.extend(others[: team_size - 1])
            reason = "put myself on to control the outcome"

        self._record_reason(turn, self._current_round_num(), "proposed", reason)
        return sorted(team)

    async def vote_on_team(self, turn: int, round_num: int, leader: int, team: List[int]) -> bool:
        approve, reason = self._decide_team_vote(round_num, team)
        self._record_reason(turn, round_num, "approved" if approve else "rejected", reason)
        return approve

    def _decide_team_vote(self, round_num: int, team: List[int]):
        # Hammer (round 4) auto-approves
        if round_num >= 4:
            return True, "hammer round auto-approves"

        if self.side:
            if self.player_id in team:
                return True, "I am on the team"
            scores = [self.suspicion(p) for p in team]
            if all(s is not None for s in scores):
                avg_suspicion = sum(scores) / len(team)
                return avg_suspicion < 0.45, f"average suspicion {avg_suspicion:.2f}"
            approve = self.rng.random() > 0.40
            return approve, "no strong read yet"

        # Evil approves if at least one evil is on team
        has_evil = any(p in self.private_info.get("seen_evil", []) or p == self.player_id for p in team)
        return has_evil, "an evil player is on it" if has_evil else "no evil player on it"

    async def vote_on_quest(self, turn: int, team: List[int]) -> bool:
        if self.side:
            return True  # Good must vote Pass
        # Evil fails unless it's strategic to pass (e.g. first quest bluffing 30% of the time)
        if turn == 0 and self.rng.random() < 0.30:
            return True
        return False

    async def assassinate(self) -> int:
        guess = self.merlin_guess()
        if guess is not None:
            return guess
        good_players = [p for p in range(self.num_players) if p not in self.private_info.get("seen_evil", []) and p != self.player_id]
        if not good_players:
            return 0
        return self.rng.choice(good_players)


class HumanAgent(Agent):
    """
    Agent controlled by a human (via text input or Higgs Realtime speech).
    """

    def __init__(self, player_id: int, role: Role, num_players: int = 5):
        super().__init__(player_id, role, num_players, condition="human")
        self.input_callback = None

    async def team_discussion(self, turn: int, round_num: int, leader: int, team_size: int) -> str:
        prompt = f"\n[Human Player {self.player_id} - {ROLE_NAMES[self.role]}] Enter your spoken statement: "
        return input(prompt).strip()

    async def propose_team(self, turn: int, team_size: int) -> List[int]:
        while True:
            try:
                line = input(f"[Human Leader] Propose {team_size} players (e.g. 0 1): ")
                team = [int(x) for x in line.replace(",", " ").split()]
                if len(team) == team_size:
                    return sorted(team)
            except Exception:
                pass
            print(f"Invalid team. Please enter exactly {team_size} player indices.")

    async def vote_on_team(self, turn: int, round_num: int, leader: int, team: List[int]) -> bool:
        while True:
            resp = input(f"[Human Player {self.player_id}] Approve team {team}? (y/n): ").strip().lower()
            if resp in ("y", "yes", "1"):
                return True
            if resp in ("n", "no", "0"):
                return False

    async def vote_on_quest(self, turn: int, team: List[int]) -> bool:
        if self.side:
            print(f"[Human Player {self.player_id}] Good player: automatically casting PASS.")
            return True
        while True:
            resp = input(f"[Human Evil Player {self.player_id}] Pass (p) or Fail (f) quest? ").strip().lower()
            if resp in ("p", "pass"):
                return True
            if resp in ("f", "fail"):
                return False

    async def assassinate(self) -> int:
        while True:
            try:
                t = int(input("[Assassin] Choose target player index to assassinate: "))
                if 0 <= t < self.num_players and t != self.player_id:
                    return t
            except Exception:
                pass
            print("Invalid target.")
