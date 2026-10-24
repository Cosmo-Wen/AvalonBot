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
        # Check if any quest has failed so far in the game
        any_failed_quest = any("FAILED" in h for h in self.chat_history)

        top_suspect = 0
        safest_partner = (self.player_id + 1) % self.num_players
        if self.belief_graph:
            suspects = [p for p in self.belief_graph.get_top_suspects(self.num_players) if p != self.player_id]
            if suspects:
                top_suspect = suspects[0]
            safest = [p for p in self.belief_graph.get_least_suspects(self.num_players) if p != self.player_id]
            if safest:
                safest_partner = safest[0]

        # Leader utterances
        if self.player_id == leader:
            if any_failed_quest:
                leader_templates = [
                    f"<|emotion:anger|><|prosody:expressiveness_high|>The previous quest was an absolute disaster! <|prosody:pause|>As leader, I will not allow traitors to sabotage Quest {turn + 1}. I'm drafting {team_size} players with clean records!",
                    f"<|style:shouting|><|emotion:anger|><|prosody:expressiveness_high|>Listen to me right now! <|prosody:pause|>We cannot afford another failed mission! I am taking charge and proposing {team_size} players who will actually vote Pass!",
                    f"<|emotion:determination|><|prosody:expressiveness_high|>The kingdom is on the brink of collapse! As leader for Quest {turn + 1}, I have reviewed past votes and I am selecting a disciplined team of size {team_size}.",
                ]
            else:
                leader_templates = [
                    f"<|emotion:determination|><|prosody:expressiveness_high|>Listen up, table! As leader for Quest {turn + 1}, we need a clean victory. I'm selecting {team_size} players with proven loyalty!",
                    f"<|emotion:enthusiasm|><|prosody:expressiveness_high|>This is our moment! <|prosody:pause|>As leader for Quest {turn + 1}, I am taking responsibility and proposing {team_size} players I genuinely trust.",
                    f"<|emotion:determination|><|prosody:expressiveness_high|>The entire realm is watching us! As leader, I will pick {team_size} players who will fight honorably for Arthur.",
                ]
            return self.rng.choice(leader_templates)

        # Merlin utterances (whispered contemplation or tense warning)
        if self.role == Role.MERLIN:
            if any_failed_quest:
                merlin_templates = [
                    f"<|style:whispering|><|emotion:contemplation|><|prosody:expressiveness_high|>Listen closely... <|prosody:pause|>Do not let anger cloud your judgment. Look at who approved that failed mission. Player {top_suspect} is leading us into a trap.",
                    f"<|emotion:anger|><|prosody:expressiveness_high|>Do not be blind! <|prosody:pause|>If you put Player {top_suspect} on this quest, Arthur's kingdom will fall to the shadows!",
                    f"<|style:whispering|><|emotion:contemplation|><|prosody:expressiveness_high|>The stars warn of grave betrayal... Player {safest_partner} is far safer than Player {top_suspect}. Do not ignore this warning.",
                ]
            else:
                merlin_templates = [
                    f"<|style:whispering|><|emotion:contemplation|><|prosody:expressiveness_high|>Listen closely... <|prosody:pause|>I advise extreme caution regarding Player {top_suspect}. Look at their voting record!",
                    f"<|style:whispering|><|emotion:contemplation|><|prosody:expressiveness_high|>If we want Quest {turn + 1} to succeed, Player {safest_partner} is a much safer choice than Player {top_suspect}. Tread carefully.",
                    f"<|emotion:contemplation|><|prosody:expressiveness_high|>Wait... <|prosody:pause|>look at how the approvals lined up earlier. We cannot afford to rush into another trap.",
                ]
            return self.rng.choice(merlin_templates)

        # Loyal Servant utterances (high-octane anger, outrage over sabotage, fierce loyalty)
        if self.side:
            if round_num >= 3:
                # Nearing the hammer: panic & fierce urgency
                servant_templates = [
                    f"<|emotion:fear|><|prosody:speed_fast|><|prosody:expressiveness_high|>Wait! <|prosody:pause|>We are at round {round_num + 1} and right at the hammer! If this team fails, evil wins the entire game! We have to vote carefully!",
                    f"<|style:shouting|><|emotion:anger|><|prosody:expressiveness_high|>This is the hammer round! <|prosody:pause|>Do NOT let Player {top_suspect} onto this mission, or Arthur's realm is finished!",
                ]
            elif any_failed_quest:
                # Post-sabotage fury & direct accusation
                servant_templates = [
                    f"<|style:shouting|><|emotion:anger|><|prosody:expressiveness_high|>Someone backstabbed Arthur on that mission! <|prosody:pause|>Player {top_suspect}, you supported that lineup! How dare you sit there looking innocent?!",
                    f"<|emotion:anger|><|prosody:speed_fast|><|prosody:expressiveness_high|>I am furious! <|prosody:pause|>We were sabotaged! Stop making excuses for Player {top_suspect} and look at the evidence!",
                    f"<|emotion:anger|><|prosody:expressiveness_high|>I swear by Arthur that I am 100% loyal! Put me on this mission if you want a Pass, and keep Player {top_suspect} off!",
                ]
            else:
                # Early game earnest questioning
                servant_templates = [
                    f"<|emotion:anger|><|prosody:speed_fast|><|prosody:expressiveness_high|>Wait, hold on! <|prosody:pause|>Player {top_suspect}'s actions make me suspicious! Why are they supporting that risky lineup?!",
                    f"<|emotion:enthusiasm|><|prosody:expressiveness_high|>I know with certainty that my heart is loyal to the King! Put me on the field and we will bring home a Pass!",
                    f"<|emotion:determination|><|prosody:expressiveness_high|>We only need three clean passes to win. I trust Player {safest_partner} ten times more than Player {top_suspect}!",
                ]
            return self.rng.choice(servant_templates)

        # Evil utterances (Minion / Assassin: shouting defense, mocking amusement, feigning betrayal)
        else:
            seen_evil = self.private_info.get("seen_evil", [])
            innocent_targets = [p for p in range(self.num_players) if p not in seen_evil and p != self.player_id]
            target = self.rng.choice(innocent_targets) if innocent_targets else top_suspect

            if any_failed_quest:
                evil_templates = [
                    f"<|style:shouting|><|emotion:anger|><|prosody:expressiveness_high|>How dare you scream at me?! <|prosody:pause|>I put my life on the line for Arthur while Player {target} sat back and manipulated everyone!",
                    f"<|emotion:amusement|><|prosody:speed_slow|><|prosody:expressiveness_high|><|sfx:laughter|>Haha! <|prosody:pause|>Are you seriously pointing at me? You are blinded by paranoia while the real traitor, Player {target}, walks free!",
                    f"<|emotion:anger|><|prosody:speed_fast|><|prosody:expressiveness_high|>Stop lying right to my face! <|prosody:pause|>Player {target} is deflecting blame onto me because their own record is filthy!",
                ]
            else:
                evil_templates = [
                    f"<|emotion:anger|><|prosody:expressiveness_high|>Are you seriously accusing me?! <|prosody:pause|>I have fought honorably for Arthur from day one! You're letting the real spies escape!",
                    f"<|emotion:amusement|><|prosody:speed_slow|><|prosody:expressiveness_high|><|sfx:laughter|>Haha! <|prosody:pause|>Why is everyone ignoring Player {target}? Their behavior has been suspect from the very start!",
                    f"<|emotion:determination|><|prosody:expressiveness_high|>I am ready to march right now and prove my loyalty on the battlefield! Put me on the quest team!",
                ]
            return self.rng.choice(evil_templates)

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
