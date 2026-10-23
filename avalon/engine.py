"""
Core 5-Player Avalon Game Environment.

Roles:
- Good (3): Merlin (0), Loyal Servant (1), Loyal Servant (2)
- Evil (2): Minion of Mordred (3), Assassin (4)

Quests:
- 5 Quests with team sizes: [2, 3, 2, 3, 3]
- 1 Fail required to fail any quest.
- Max 5 team proposal rounds per quest. On round 5, proposal auto-passes (the "hammer").
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional, Set, Tuple
import random


class Role(IntEnum):
    MERLIN = 0
    LOYAL_SERVANT = 1
    MINION = 2
    ASSASSIN = 3


ROLE_NAMES = {
    Role.MERLIN: "Merlin",
    Role.LOYAL_SERVANT: "Loyal Servant",
    Role.MINION: "Minion",
    Role.ASSASSIN: "Assassin",
}

ROLE_SIDES = {
    Role.MERLIN: True,         # Good
    Role.LOYAL_SERVANT: True,  # Good
    Role.MINION: False,        # Evil
    Role.ASSASSIN: False,      # Evil
}


class Phase(IntEnum):
    TEAM_SELECTION = 0
    TEAM_VOTING = 1
    QUEST_VOTING = 2
    ASSASSINATION = 3
    GAME_OVER = 4


PHASE_NAMES = {
    Phase.TEAM_SELECTION: "Team Selection",
    Phase.TEAM_VOTING: "Team Voting",
    Phase.QUEST_VOTING: "Quest Voting",
    Phase.ASSASSINATION: "Assassination",
    Phase.GAME_OVER: "Game Over",
}


@dataclass
class QuestRecord:
    turn: int
    team: List[int]
    leader: int
    rounds_taken: int
    num_fails: int
    success: bool


@dataclass
class RoundVoteRecord:
    turn: int
    round_num: int
    leader: int
    team: List[int]
    votes: Dict[int, bool]
    approved: bool


class AvalonEngine:
    """
    Single-source-of-truth 5-Player Avalon rules engine.
    Completely instance-based (no shared class state).
    """

    NUM_PLAYERS: int = 5
    NUM_GOOD: int = 3
    NUM_EVIL: int = 2
    QUEST_SIZES: List[int] = [2, 3, 2, 3, 3]
    FAILS_REQUIRED: List[int] = [1, 1, 1, 1, 1]
    MAX_ROUNDS_PER_QUEST: int = 5

    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)
        self.player_roles: Dict[int, Role] = {}
        self.player_sides: Dict[int, bool] = {}  # True = Good, False = Evil

        self.turn: int = 0         # Quest index (0 to 4)
        self.round_num: int = 0    # Proposal attempt within quest (0 to 4)
        self.leader: int = 0       # Current quest leader (player id 0 to 4)
        self.phase: Phase = Phase.TEAM_SELECTION

        self.current_team: List[int] = []
        self.quest_results: List[bool] = []
        self.quest_history: List[QuestRecord] = []
        self.vote_history: List[RoundVoteRecord] = []

        self.assassination_target: Optional[int] = None
        self.good_victory: Optional[bool] = None
        self.game_over: bool = False
        self.win_reason: str = ""

    def reset(
        self,
        preset_roles: Optional[Dict[int, Role]] = None,
        preset_leader: Optional[int] = None,
    ) -> Dict[int, Role]:
        """
        Initializes a fresh game with assigned roles and starting leader.
        """
        self.turn = 0
        self.round_num = 0
        self.phase = Phase.TEAM_SELECTION
        self.current_team = []
        self.quest_results = []
        self.quest_history = []
        self.vote_history = []
        self.assassination_target = None
        self.good_victory = None
        self.game_over = False
        self.win_reason = ""

        if preset_roles is not None:
            self.player_roles = dict(preset_roles)
        else:
            # 5 players: 1 Merlin, 2 Servants, 1 Minion, 1 Assassin
            pool = [
                Role.MERLIN,
                Role.LOYAL_SERVANT,
                Role.LOYAL_SERVANT,
                Role.MINION,
                Role.ASSASSIN,
            ]
            self.rng.shuffle(pool)
            self.player_roles = {i: pool[i] for i in range(self.NUM_PLAYERS)}

        self.player_sides = {i: ROLE_SIDES[role] for i, role in self.player_roles.items()}

        if preset_leader is not None:
            self.leader = preset_leader % self.NUM_PLAYERS
        else:
            self.leader = self.rng.randint(0, self.NUM_PLAYERS - 1)

        return self.player_roles

    def get_merlin(self) -> int:
        for player, role in self.player_roles.items():
            if role == Role.MERLIN:
                return player
        raise ValueError("Merlin not found in player roles")

    def get_assassin(self) -> int:
        for player, role in self.player_roles.items():
            if role == Role.ASSASSIN:
                return player
        raise ValueError("Assassin not found in player roles")

    def get_evil_players(self) -> List[int]:
        return [p for p, side in self.player_sides.items() if not side]

    def get_good_players(self) -> List[int]:
        return [p for p, side in self.player_sides.items() if side]

    def get_required_team_size(self) -> int:
        return self.QUEST_SIZES[self.turn]

    def get_private_info(self, player: int) -> Dict[str, any]:
        """
        Returns starting private role knowledge for the specified player.
        - Merlin sees who is Evil (both Minion and Assassin).
        - Evil players (Minion & Assassin) see each other.
        - Loyal Servants only know their own identity.
        """
        role = self.player_roles[player]
        side = self.player_sides[player]
        evil_players = self.get_evil_players()

        info = {
            "player": player,
            "role": role,
            "role_name": ROLE_NAMES[role],
            "side": side,
            "side_name": "Good" if side else "Evil",
            "seen_evil": [],
        }

        if role == Role.MERLIN:
            # Merlin sees which players are evil, but not their specific roles
            info["seen_evil"] = [p for p in evil_players if p != player]
        elif not side:
            # Evil sees other evil players
            info["seen_evil"] = [p for p in evil_players if p != player]

        return info

    def choose_team(self, leader: int, team: List[int]) -> Tuple[Phase, bool]:
        """
        Phase 0: Leader proposes a team.
        """
        if self.game_over:
            raise RuntimeError("Cannot choose team: game is already over")
        if self.phase != Phase.TEAM_SELECTION:
            raise RuntimeError(f"Expected TEAM_SELECTION phase, got {self.phase.name}")
        if leader != self.leader:
            raise ValueError(f"Player {leader} is not the current quest leader (expected {self.leader})")

        req_size = self.get_required_team_size()
        cleaned_team = sorted(list(set(team)))
        if len(cleaned_team) != req_size:
            raise ValueError(f"Invalid team size: got {len(cleaned_team)}, expected {req_size}")
        if any(p < 0 or p >= self.NUM_PLAYERS for p in cleaned_team):
            raise ValueError(f"Team contains invalid player indices: {cleaned_team}")

        self.current_team = cleaned_team
        self.phase = Phase.TEAM_VOTING
        return self.phase, self.game_over

    def vote_on_team(self, votes: Dict[int, bool]) -> Tuple[Phase, bool, bool]:
        """
        Phase 1: All players vote on proposed team.
        Returns: (next_phase, game_over, team_approved)
        """
        if self.game_over:
            raise RuntimeError("Cannot vote on team: game is already over")
        if self.phase != Phase.TEAM_VOTING:
            raise RuntimeError(f"Expected TEAM_VOTING phase, got {self.phase.name}")
        if len(votes) != self.NUM_PLAYERS:
            raise ValueError(f"Expected {self.NUM_PLAYERS} votes, got {len(votes)}")

        # Round 5 (hammer): automatic approval
        if self.round_num == self.MAX_ROUNDS_PER_QUEST - 1:
            approved = True
        else:
            approve_count = sum(1 for v in votes.values() if v)
            approved = approve_count > (self.NUM_PLAYERS / 2)  # Strict majority (>2 of 5)

        self.vote_history.append(
            RoundVoteRecord(
                turn=self.turn,
                round_num=self.round_num,
                leader=self.leader,
                team=list(self.current_team),
                votes=dict(votes),
                approved=approved,
            )
        )

        if approved:
            self.phase = Phase.QUEST_VOTING
        else:
            self.round_num += 1
            self.leader = (self.leader + 1) % self.NUM_PLAYERS
            self.phase = Phase.TEAM_SELECTION

        return self.phase, self.game_over, approved

    def vote_on_quest(self, votes: Dict[int, bool]) -> Tuple[Phase, bool, bool, int]:
        """
        Phase 2: Members of the quest team cast secret pass/fail votes.
        True = Pass, False = Fail.
        Returns: (next_phase, game_over, quest_success, num_fails)
        """
        if self.game_over:
            raise RuntimeError("Cannot vote on quest: game is already over")
        if self.phase != Phase.QUEST_VOTING:
            raise RuntimeError(f"Expected QUEST_VOTING phase, got {self.phase.name}")

        req_size = self.get_required_team_size()
        team_set = set(self.current_team)
        if set(votes.keys()) != team_set:
            raise ValueError(f"Votes must come exactly from team members {self.current_team}, got {list(votes.keys())}")

        # Enforce that Good players CANNOT fail a quest
        for player, vote in votes.items():
            if self.player_sides[player] and not vote:
                raise ValueError(f"Good player {player} cannot vote Fail on a quest")

        num_fails = sum(1 for v in votes.values() if not v)
        quest_success = num_fails < self.FAILS_REQUIRED[self.turn]

        self.quest_results.append(quest_success)
        self.quest_history.append(
            QuestRecord(
                turn=self.turn,
                team=list(self.current_team),
                leader=self.leader,
                rounds_taken=self.round_num + 1,
                num_fails=num_fails,
                success=quest_success,
            )
        )

        # Advance to next quest leader
        self.leader = (self.leader + 1) % self.NUM_PLAYERS
        self.round_num = 0
        self.turn += 1

        # Check win conditions
        failed_quests = sum(1 for res in self.quest_results if not res)
        passed_quests = sum(1 for res in self.quest_results if res)

        if failed_quests >= 3:
            # Evil wins immediately by missions
            self.game_over = True
            self.good_victory = False
            self.phase = Phase.GAME_OVER
            self.win_reason = "Evil wins: 3 quests failed."
        elif passed_quests >= 3:
            # Good passed 3 quests -> Assassin gets a chance
            self.phase = Phase.ASSASSINATION
        else:
            self.phase = Phase.TEAM_SELECTION

        return self.phase, self.game_over, quest_success, num_fails

    def assassinate(self, assassin: int, target: int) -> Tuple[Phase, bool, bool]:
        """
        Phase 3: Assassin guesses Merlin.
        Returns: (next_phase, game_over, good_victory)
        """
        if self.game_over:
            raise RuntimeError("Cannot assassinate: game is already over")
        if self.phase != Phase.ASSASSINATION:
            raise RuntimeError(f"Expected ASSASSINATION phase, got {self.phase.name}")
        if self.player_roles[assassin] != Role.ASSASSIN:
            raise ValueError(f"Player {assassin} is not the Assassin")
        if target < 0 or target >= self.NUM_PLAYERS:
            raise ValueError(f"Invalid assassination target: {target}")
        if not self.player_sides[target]:
            raise ValueError(f"Assassin cannot target an evil player ({target})")

        self.assassination_target = target
        merlin = self.get_merlin()
        hit_merlin = (target == merlin)

        self.game_over = True
        self.phase = Phase.GAME_OVER

        if hit_merlin:
            self.good_victory = False
            self.win_reason = f"Evil wins: Assassin shot Merlin (Player {merlin})."
        else:
            self.good_victory = True
            self.win_reason = f"Good wins: 3 quests succeeded and Merlin (Player {merlin}) survived assassination."

        return self.phase, self.game_over, self.good_victory
