"""
Structured Belief Graph for Avalon Agents.

Tracks per-player probability of being Evil (P(evil)) and evidence edges
(proposals, votes, quest outcomes, accusations) tagged by turn and round.
Formats into a compact table for prompt injection, and computes evaluation
metrics (Brier score, Spy-identification accuracy).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class EvidenceEdge:
    turn: int
    round_num: int
    kind: str  # "proposed", "voted_approve", "voted_reject", "quest_member", "accusation"
    note: str


class BeliefGraph:
    """
    Per-agent belief store over the table.
    """

    def __init__(self, owner: int, num_players: int = 5, known_evil: Optional[List[int]] = None):
        self.owner = owner
        self.num_players = num_players
        self.known_evil = set(known_evil or [])

        # Initial prior: 2 evils out of 4 other players = 0.5 (or 2/4 = 0.5 prior)
        # If owner is evil, they know true evils:
        self.p_evil: Dict[int, float] = {}
        for p in range(num_players):
            if p == owner:
                self.p_evil[p] = 0.0  # Agent knows self is not opponent evil
            elif p in self.known_evil:
                self.p_evil[p] = 1.0  # Confirmed evil
            else:
                self.p_evil[p] = 0.5  # Neutral prior

        self.evidence: Dict[int, List[EvidenceEdge]] = {p: [] for p in range(num_players)}

    def add_evidence(self, player: int, turn: int, round_num: int, kind: str, note: str):
        if player in self.evidence:
            self.evidence[player].append(EvidenceEdge(turn=turn, round_num=round_num, kind=kind, note=note))

    def set_p_evil(self, player: int, prob: float):
        if player == self.owner:
            return
        if player in self.known_evil:
            self.p_evil[player] = 1.0
            return
        self.p_evil[player] = max(0.01, min(0.99, float(prob)))

    def adjust_p_evil(self, player: int, delta: float):
        if player == self.owner or player in self.known_evil:
            return
        curr = self.p_evil[player]
        self.p_evil[player] = max(0.01, min(0.99, curr + delta))

    def update_deterministic_vote_rules(
        self,
        turn: int,
        round_num: int,
        leader: int,
        team: List[int],
        votes: Dict[int, bool],
        approved: bool,
    ):
        """
        Deterministic evidence logging on team proposal & voting (Condition C).
        """
        self.add_evidence(
            leader,
            turn,
            round_num,
            "proposed",
            f"Proposed team {team}",
        )

        for p, v in votes.items():
            self.add_evidence(
                p,
                turn,
                round_num,
                "voted_approve" if v else "voted_reject",
                f"{'Approved' if v else 'Rejected'} team {team}",
            )

    def update_deterministic_quest_outcome(
        self,
        turn: int,
        team: List[int],
        num_fails: int,
        success: bool,
    ):
        """
        Deterministic belief adjustments upon quest resolution (Condition C).
        If quest failed with N fails, suspicion on team members rises significantly.
        If quest succeeded, suspicion on team members drops slightly.
        """
        for p in team:
            if p == self.owner:
                continue

            if not success:
                # Quest failed: at least one person on team is definitely evil!
                prob_increase = 0.35 * (num_fails / len(team))
                self.adjust_p_evil(p, prob_increase)
                self.add_evidence(
                    p,
                    turn,
                    0,
                    "quest_member",
                    f"Was on failed Quest {turn + 1} ({num_fails} fail)",
                )
            else:
                # Quest succeeded: mildly lowers evil probability
                self.adjust_p_evil(p, -0.10)
                self.add_evidence(
                    p,
                    turn,
                    0,
                    "quest_member",
                    f"Was on passed Quest {turn + 1}",
                )

    def to_prompt_table(self) -> str:
        """
        Serializes current beliefs into a compact markdown table for prompt injection.
        """
        lines = [
            "### Current Belief Table (Your Internal Analysis)",
            "| Player | P(Evil) | Status | Recent Evidence |",
            "|---|---|---|---|",
        ]

        for p in range(self.num_players):
            if p == self.owner:
                status = "You (Good)"
                recent_ev = "Self"
            elif p in self.known_evil:
                status = "Confirmed Evil"
                recent_ev = "Seen at start"
            else:
                prob = self.p_evil[p]
                if prob >= 0.70:
                    status = "High Suspect"
                elif prob <= 0.30:
                    status = "Likely Good"
                else:
                    status = "Uncertain"

                # Get latest 2 evidence notes
                evs = self.evidence[p][-2:]
                recent_ev = "; ".join(e.note for e in evs) if evs else "No action yet"

            prob_str = f"{self.p_evil[p]:.2f}" if p != self.owner else "0.00"
            lines.append(f"| Player {p} | {prob_str} | {status} | {recent_ev} |")

        return "\n".join(lines)

    def get_top_suspects(self, k: int = 2) -> List[int]:
        """
        Returns the top-k players with highest P(evil), excluding owner.
        """
        candidates = [(p, self.p_evil[p]) for p in range(self.num_players) if p != self.owner]
        candidates.sort(key=lambda x: x[1], reverse=True)
        return [p for p, _ in candidates[:k]]

    def is_spy_id_accurate(self, true_evil_players: Set[int]) -> bool:
        """
        Checks whether the top-2 suspects are exactly the two evil players.
        """
        top_2 = set(self.get_top_suspects(k=2))
        return top_2 == true_evil_players

    def brier_score(self, true_evil_players: Set[int]) -> float:
        """
        Brier score = mean squared error of P(evil) across all other players.
        Lower is better (0.0 = perfect calibration).
        """
        others = [p for p in range(self.num_players) if p != self.owner]
        if not others:
            return 0.0
        total_sq_err = 0.0
        for p in others:
            y = 1.0 if p in true_evil_players else 0.0
            p_hat = self.p_evil[p]
            total_sq_err += (p_hat - y) ** 2
        return total_sq_err / len(others)
