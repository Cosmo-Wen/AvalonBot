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
from .belief_graph import BeliefGraph


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
    ):
        self.player_id = player_id
        self.role = role
        self.side = ROLE_SIDES[role]
        self.num_players = num_players
        self.condition = condition
        self.rng = random.Random(seed)

        # Belief graph initialized if in condition B or C, or if owner needs it for eval
        self.belief_graph: Optional[BeliefGraph] = None
        if self.condition in ("belief_graph", "rule_graph") or self.side:
            # Good players always track beliefs for evaluation metrics
            self.belief_graph = BeliefGraph(owner=player_id, num_players=num_players)

        self.chat_history: List[str] = []
        self.private_info: Dict[str, Any] = {}

    def set_private_info(self, info: Dict[str, Any]):
        self.private_info = info
        if self.belief_graph and info.get("seen_evil"):
            self.belief_graph.known_evil = set(info["seen_evil"])
            for e in info["seen_evil"]:
                self.belief_graph.set_p_evil(e, 1.0)

    def observe_event(self, event_type: str, data: Dict[str, Any]):
        """
        Observes a game event (utterance, proposal, team vote, quest outcome).
        Updates chat history and belief graph accordingly.
        """
        if event_type == "utterance":
            speaker = data["speaker"]
            text = data["text"]
            self.chat_history.append(f"Player {speaker}: \"{text}\"")

        elif event_type == "team_proposed":
            turn = data["turn"]
            round_num = data["round_num"]
            leader = data["leader"]
            team = data["team"]
            self.chat_history.append(f"[System] Quest {turn + 1}, Round {round_num + 1}: Player {leader} proposed team {team}.")

        elif event_type == "team_vote_result":
            turn = data["turn"]
            round_num = data["round_num"]
            leader = data["leader"]
            team = data["team"]
            votes = data["votes"]
            approved = data["approved"]
            res_str = "APPROVED" if approved else "REJECTED"
            vote_summary = ", ".join(f"P{p}:{'Y' if v else 'N'}" for p, v in votes.items())
            self.chat_history.append(f"[System] Vote on team {team} was {res_str} ({vote_summary}).")

            if self.belief_graph and self.condition in ("belief_graph", "rule_graph"):
                self.belief_graph.update_deterministic_vote_rules(turn, round_num, leader, team, votes, approved)

        elif event_type == "quest_result":
            turn = data["turn"]
            team = data["team"]
            success = data["success"]
            num_fails = data["num_fails"]
            outcome_str = "SUCCEEDED" if success else f"FAILED with {num_fails} fail(s)"
            self.chat_history.append(f"[System] Quest {turn + 1} {outcome_str}! Team was {team}.")

            if self.belief_graph:
                self.belief_graph.update_deterministic_quest_outcome(turn, team, num_fails, success)

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

    async def team_discussion(self, turn: int, round_num: int, leader: int, team_size: int) -> str:
        if self.player_id == leader:
            return f"As leader for Quest {turn + 1}, I will propose a trustworthy team of size {team_size}."
        if self.side:
            if self.belief_graph:
                top_suspect = self.belief_graph.get_top_suspects(1)[0]
                return f"I want to make sure Player {top_suspect} is not on this mission."
            return f"I support building a clean good team for Quest {turn + 1}."
        else:
            return f"I am a loyal servant of Arthur. Put me on the quest team."

    async def propose_team(self, turn: int, team_size: int) -> List[int]:
        team = [self.player_id]

        if self.side:
            # Good: pick least suspicious players
            if self.belief_graph:
                candidates = [(p, self.belief_graph.p_evil[p]) for p in range(self.num_players) if p != self.player_id]
                candidates.sort(key=lambda x: x[1])  # lowest P(evil) first
                for p, _ in candidates:
                    if len(team) < team_size:
                        team.append(p)
            else:
                others = [p for p in range(self.num_players) if p != self.player_id]
                self.rng.shuffle(others)
                team.extend(others[: team_size - 1])
        else:
            # Evil: leader includes self and preferably one good player to blend in
            others = [p for p in range(self.num_players) if p != self.player_id]
            self.rng.shuffle(others)
            team.extend(others[: team_size - 1])

        return sorted(team)

    async def vote_on_team(self, turn: int, round_num: int, leader: int, team: List[int]) -> bool:
        # Hammer (round 4) auto-approves
        if round_num >= 4:
            return True

        if self.side:
            # Good approves if self is on team or team has low suspicion
            if self.player_id in team:
                return True
            if self.belief_graph:
                avg_suspicion = sum(self.belief_graph.p_evil[p] for p in team) / len(team)
                return avg_suspicion < 0.45
            return self.rng.random() > 0.40
        else:
            # Evil approves if at least one evil is on team
            has_evil = any(p in self.private_info.get("seen_evil", []) or p == self.player_id for p in team)
            return has_evil

    async def vote_on_quest(self, turn: int, team: List[int]) -> bool:
        if self.side:
            return True  # Good must vote Pass
        # Evil fails unless it's strategic to pass (e.g. first quest bluffing 30% of the time)
        if turn == 0 and self.rng.random() < 0.30:
            return True
        return False

    async def assassinate(self) -> int:
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
