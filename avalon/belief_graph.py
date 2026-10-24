"""
Knowledge graph and beliefs for one player's memory (see MEMORY_MODEL.md).

- KnowledgeGraph: team nodes plus typed edges. Every edge cites the log entries
  (by seq) it came from.
- PairBelief: a Loyal Servant's P(evil), stored as weights over the possible
  evil pairs among its 4 opponents, so the marginals always sum to 2.
"""

from dataclasses import dataclass, field
from itertools import combinations
from typing import Dict, List, Optional, Sequence, Tuple, Union


ACTION_EDGES = ("member_of", "proposed", "voted_approve", "voted_reject")
PLAYER_TALK_EDGES = ("accused", "defended")
TEAM_TALK_EDGES = ("backed_team", "opposed_team")
TALK_EDGES = PLAYER_TALK_EDGES + TEAM_TALK_EDGES + ("claimed_role",)
SELF_EDGES = ("i_said", "i_reasoned")

MAX_QUOTE_WORDS = 10
MAX_NOTE_WORDS = 15
MAX_REASON_WORDS = 20

# Condition C vote factors. Fixed before launch; never tune them on results.
APPROVE_FAILED = 2.0
REJECT_FAILED = 0.5

# Evil P(Merlin) factors (demo only). Fixed before launch; never tune them on results.
MERLIN_ACCURATE_VOTE = 1.5
MERLIN_PIVOTAL_REJECT = 1.5
MERLIN_EARLY_ACCUSATION = 2.0

SUM_TOLERANCE = 0.05
FORCED_TOLERANCE = 0.01


def clip_words(text: str, max_words: int) -> str:
    return " ".join(str(text).split()[:max_words])


def team_label(quest: int, attempt: int) -> str:
    return f"Q{quest}.{attempt}"


@dataclass
class TeamNode:
    label: str
    quest: int
    attempt: int
    leader: int
    members: List[int]
    votes: Dict[int, bool] = field(default_factory=dict)
    approved: Optional[bool] = None
    fails: Optional[int] = None
    success: Optional[bool] = None

    @property
    def failed(self) -> bool:
        return self.success is False


@dataclass
class Edge:
    id: int
    type: str
    src: int
    dst: Union[int, str, None]
    seq: int
    quest: int
    attempt: int
    sources: List[int]
    quote: str = ""
    role: str = ""
    action: str = ""
    reason: str = ""


class KnowledgeGraph:
    """
    Players and teams as nodes, evidence as edges. Owned by exactly one player.
    """

    def __init__(self, owner: int, num_players: int = 5):
        self.owner = owner
        self.num_players = num_players
        self.teams: Dict[str, TeamNode] = {}
        self.edges: List[Edge] = []
        # Fail cards the owner itself played, by team label. They explain that many of the team's fails.
        self.own_fails: Dict[str, int] = {}

    def _add(
        self,
        type: str,
        src: int,
        dst: Union[int, str, None],
        seq: int,
        quest: int,
        attempt: int,
        sources: Sequence[int],
        **extra: str,
    ) -> Edge:
        edge = Edge(
            id=len(self.edges),
            type=type,
            src=src,
            dst=dst,
            seq=seq,
            quest=quest,
            attempt=attempt,
            sources=list(sources),
            **extra,
        )
        self.edges.append(edge)
        return edge

    # Action edges, written by code from delivered events

    def add_proposal(self, seq: int, quest: int, attempt: int, leader: int, members: Sequence[int]) -> TeamNode:
        label = team_label(quest, attempt)
        team = TeamNode(label=label, quest=quest, attempt=attempt, leader=leader, members=sorted(members))
        self.teams[label] = team
        self._add("proposed", leader, label, seq, quest, attempt, [seq])
        return team

    def add_team_vote(self, seq: int, quest: int, attempt: int, votes: Dict[int, bool], approved: bool) -> None:
        label = team_label(quest, attempt)
        team = self.teams[label]
        team.votes = dict(votes)
        team.approved = approved
        for player, approve in sorted(votes.items()):
            kind = "voted_approve" if approve else "voted_reject"
            self._add(kind, player, label, seq, quest, attempt, [seq])

    def add_quest_result(self, seq: int, quest: int, attempt: int, fails: int, success: bool) -> TeamNode:
        label = team_label(quest, attempt)
        team = self.teams[label]
        team.fails = fails
        team.success = success
        for player in team.members:
            self._add("member_of", player, label, seq, quest, attempt, [seq])
        return team

    # Talk and self edges

    def add_talk_edge(
        self,
        type: str,
        src: int,
        dst: Union[int, str],
        seq: int,
        quest: int,
        attempt: int,
        sources: Sequence[int],
        quote: str = "",
        role: str = "",
    ) -> Optional[Edge]:
        """Adds a talk edge if it is well-formed and new. Returns None otherwise."""
        if type in PLAYER_TALK_EDGES:
            if not isinstance(dst, int) or not (0 <= dst < self.num_players) or dst == src:
                return None
        elif type in TEAM_TALK_EDGES:
            if dst not in self.teams:
                return None
        elif type == "claimed_role":
            if not role:
                return None
            dst = src
        else:
            return None

        for e in self.edges:
            if e.type == type and e.src == src and e.dst == dst and e.seq == seq:
                return None

        return self._add(
            type, src, dst, seq, quest, attempt, sources,
            quote=clip_words(quote, MAX_QUOTE_WORDS),
            role=role,
        )

    def add_said(self, seq: int, quest: int, attempt: int, text: str) -> Edge:
        return self._add("i_said", self.owner, None, seq, quest, attempt, [seq], quote=clip_words(text, MAX_QUOTE_WORDS))

    def add_reasoned(self, seq: int, quest: int, attempt: int, action: str, label: str, reason: str) -> Edge:
        return self._add(
            "i_reasoned", self.owner, label, seq, quest, attempt, [seq],
            action=action,
            reason=clip_words(reason, MAX_REASON_WORDS),
        )

    # Queries

    def failed_teams(self) -> List[TeamNode]:
        return [t for t in self.teams.values() if t.failed]

    def edges_of(self, types: Sequence[str], src: Optional[int] = None) -> List[Edge]:
        return [e for e in self.edges if e.type in types and (src is None or e.src == src)]

    def evidence(self, player: int) -> List[Edge]:
        return [
            e for e in self.edges
            if e.type not in SELF_EDGES and (e.src == player or e.dst == player)
        ]

    def contradictions(self) -> List[Tuple[Edge, Edge]]:
        """
        (talk edge, vote edge) pairs where a player's vote contradicts what they said:
        accused Y then approved a team containing Y, or backed/opposed a team then
        voted the other way on it.
        """
        votes = self.edges_of(("voted_approve", "voted_reject"))
        flags: List[Tuple[Edge, Edge]] = []
        for talk in self.edges_of(("accused", "backed_team", "opposed_team")):
            for vote in votes:
                if vote.src != talk.src or vote.seq <= talk.seq:
                    continue
                if talk.type == "accused":
                    hit = vote.type == "voted_approve" and talk.dst in self.teams[vote.dst].members
                elif talk.type == "backed_team":
                    hit = vote.type == "voted_reject" and vote.dst == talk.dst
                else:
                    hit = vote.type == "voted_approve" and vote.dst == talk.dst
                if hit:
                    flags.append((talk, vote))
        return flags

    # Prompt serialization

    def _action_phrase(self, e: Edge) -> Tuple[str, str]:
        if e.type == "member_of":
            team = self.teams[e.dst]
            return "on", f"{e.dst} ({'fail' if team.failed else 'pass'})"
        verb = {"proposed": "proposed", "voted_approve": "approved", "voted_reject": "rejected"}[e.type]
        return verb, e.dst

    def _render_actions(self, player: int, recent: int = 3) -> str:
        actions = self.edges_of(ACTION_EDGES, src=player)
        hard = [e for e in actions if e.type == "member_of" and self.teams[e.dst].failed]
        other = [e for e in actions if e not in hard][-recent:]
        chosen = sorted(hard + other, key=lambda e: (e.seq, e.id))

        groups: List[Tuple[List[str], str]] = []
        for e in chosen:
            verb, obj = self._action_phrase(e)
            if verb != "on" and groups and groups[-1][1] == obj:
                groups[-1][0].append(verb)
            else:
                groups.append(([verb], obj))
        if not groups:
            return "no actions yet"
        return "; ".join(f"{', '.join(verbs)} {obj}" for verbs, obj in groups)

    def _render_talk(self, player: int, flags: List[Tuple[Edge, Edge]], recent: int = 2) -> str:
        talk = self.edges_of(TALK_EDGES, src=player)[-recent:]
        if not talk:
            return "quiet"
        parts = []
        for e in talk:
            if e.type in PLAYER_TALK_EDGES:
                text = f"{e.type} P{e.dst} (#{e.seq})"
            elif e.type == "backed_team":
                text = f"backed {e.dst} (#{e.seq})"
            elif e.type == "opposed_team":
                text = f"opposed {e.dst} (#{e.seq})"
            else:
                text = f"claimed {e.role} (#{e.seq})"
            for t, v in flags:
                if t is e:
                    verb = "approved" if v.type == "voted_approve" else "rejected"
                    text += f" ⚠ then {verb} {v.dst}"
            parts.append(text)
        return "; ".join(parts)

    def render_constraints(self) -> List[str]:
        lines = []
        for team in self.failed_teams():
            members = "{" + ",".join(str(p) for p in team.members) + "}"
            plural = "fail" if team.fails == 1 else "fails"
            head = f"Constraints: {team.label} {members} → {team.fails} {plural}"
            own = self.own_fails.get(team.label, 0)
            others_evil = team.fails - own
            if others_evil <= 0:
                lines.append(f"{head} (all played by you)")
                continue
            others = [p for p in team.members if p != self.owner]
            who = ", ".join(f"P{p}" for p in others)
            mine = f", {own} played by you" if own else ""
            lines.append(f"{head} (at least {others_evil} of {who} is evil{mine})")
        return lines

    def render_my_record(self, recent: int = 2) -> str:
        parts = []
        for e in self.edges_of(("i_reasoned",), src=self.owner)[-recent:]:
            parts.append(f'{e.action} {e.dst} ("{e.reason}")' if e.reason else f"{e.action} {e.dst}")
        for e in self.edges_of(("i_said",), src=self.owner)[-recent:]:
            parts.append(f'said "{e.quote}" (#{e.seq})')
        return "Your record: " + ("; ".join(parts) if parts else "nothing yet")

    def render_table(self, beliefs: Optional[Dict[int, float]] = None, belief_name: str = "P(evil)") -> str:
        flags = self.contradictions()
        lines = self.render_constraints()
        lines.append(f"Player | {belief_name} | Actions | Talk")
        for p in range(self.num_players):
            if p == self.owner:
                continue
            prob = f"{beliefs[p]:.2f}" if beliefs and p in beliefs else "-"
            lines.append(f"P{p} | {prob} | {self._render_actions(p)} | {self._render_talk(p, flags)}")
        lines.append(self.render_my_record())
        return "\n".join(lines)


class PairBelief:
    """
    A Loyal Servant's P(evil) over its opponents, kept coherent by construction:
    exactly `num_evil` of the opponents are evil, so beliefs are weights over the
    possible evil pairs and each player's P(evil) is the weight of the pairs containing them.
    """

    def __init__(
        self,
        owner: int,
        num_players: int = 5,
        num_evil: int = 2,
        approve_failed: float = APPROVE_FAILED,
        reject_failed: float = REJECT_FAILED,
    ):
        self.owner = owner
        self.num_evil = num_evil
        self.approve_failed = approve_failed
        self.reject_failed = reject_failed
        self.opponents = [p for p in range(num_players) if p != owner]
        self.all_pairs: List[Tuple[int, ...]] = list(combinations(self.opponents, num_evil))
        self.failed_quests: List[Tuple[List[int], int, Dict[int, bool]]] = []
        self.p_evil: Dict[int, float] = self.rule_marginals()
        self.source = "rule"

    def add_failed_quest(self, members: Sequence[int], fails: int, votes: Dict[int, bool]) -> None:
        self.failed_quests.append((list(members), fails, dict(votes)))

    @staticmethod
    def _fits(pair: Tuple[int, ...], members: Sequence[int], fails: int) -> bool:
        return len(set(pair) & set(members)) >= fails

    def _num_fitted(self, pair: Tuple[int, ...]) -> int:
        return sum(self._fits(pair, members, fails) for members, fails, _ in self.failed_quests)

    def possible_pairs(self) -> List[Tuple[int, ...]]:
        """
        Pairs that fit every failed quest. If none does (only possible when a quest result broke
        the rules, e.g. a good player played Fail), the pairs that fit the most failed quests.
        """
        best = max(self._num_fitted(pair) for pair in self.all_pairs)
        return [pair for pair in self.all_pairs if self._num_fitted(pair) == best]

    @property
    def consistent(self) -> bool:
        """False when no evil pair explains every failed quest this player has seen."""
        return any(self._num_fitted(pair) == len(self.failed_quests) for pair in self.all_pairs)

    def rule_weights(self) -> Dict[Tuple[int, ...], float]:
        weights = {}
        for pair in self.possible_pairs():
            w = 1.0
            for _, _, votes in self.failed_quests:
                for voter, approve in votes.items():
                    if voter != self.owner and voter in pair:
                        w *= self.approve_failed if approve else self.reject_failed
            weights[pair] = w
        total = sum(weights.values())
        return {pair: w / total for pair, w in weights.items()}

    def rule_marginals(self) -> Dict[int, float]:
        weights = self.rule_weights()
        return {p: sum(w for pair, w in weights.items() if p in pair) for p in self.opponents}

    def forced(self) -> Tuple[List[int], List[int]]:
        """(opponents certainly good, opponents certainly evil) given the hard constraints."""
        pairs = self.possible_pairs()
        never = [p for p in self.opponents if not any(p in pair for pair in pairs)]
        always = [p for p in self.opponents if all(p in pair for pair in pairs)]
        return never, always

    def validate(self, p_evil: Dict[int, float]) -> List[str]:
        errors: List[str] = []
        if sorted(p_evil) != self.opponents:
            return [f"p_evil must have exactly one value for each of players {self.opponents}"]
        for p, v in p_evil.items():
            if not 0.0 <= v <= 1.0:
                errors.append(f"P{p} must be between 0 and 1, got {v}")
        never, always = self.forced()
        for p in never:
            if p_evil[p] > FORCED_TOLERANCE:
                errors.append(f"P{p} cannot be evil given the failed quests, so P(evil) must be 0")
        for p in always:
            if p_evil[p] < 1.0 - FORCED_TOLERANCE:
                errors.append(f"P{p} must be evil given the failed quests, so P(evil) must be 1")
        total = sum(p_evil.values())
        if abs(total - self.num_evil) > SUM_TOLERANCE:
            errors.append(f"values must sum to {self.num_evil} (exactly {self.num_evil} of your opponents are evil), got {total:.2f}")
        pairs = self.possible_pairs()
        for members, fails, _ in self.failed_quests:
            if not all(self._fits(pair, members, fails) for pair in pairs):
                continue  # A failed quest the remaining pairs can't explain is not enforced
            others = [p for p in members if p != self.owner]
            team_sum = sum(p_evil[p] for p in others)
            if team_sum < fails - SUM_TOLERANCE:
                who = ", ".join(f"P{p}" for p in others)
                errors.append(f"{who} were on a quest with {fails} fail(s), so their values must sum to at least {fails}, got {team_sum:.2f}")
        return errors

    def set_rule(self) -> None:
        self.p_evil = self.rule_marginals()
        self.source = "rule"

    def set_llm(self, p_evil: Dict[int, float]) -> List[str]:
        errors = self.validate(p_evil)
        if not errors:
            self.p_evil = dict(p_evil)
            self.source = "llm"
        return errors

    def get(self, player: int) -> float:
        return self.p_evil.get(player, 0.0)

    def top_suspects(self, k: int = 2) -> List[int]:
        return sorted(self.opponents, key=lambda p: (-self.p_evil[p], p))[:k]

    def least_suspects(self, k: int = 2) -> List[int]:
        return sorted(self.opponents, key=lambda p: (self.p_evil[p], p))[:k]


class MerlinBelief:
    """
    An evil player's P(Merlin) over the good players (demo only). Exactly one is Merlin,
    so the values sum to 1. The signal is a good player who is too accurate:
    - votes that match the true evil team (reject teams with evil, approve clean ones)
    - a decisive reject that sank a team containing evil
    - accusing an evil player before any failed quest exposed them
    """

    def __init__(
        self,
        owner: int,
        known_evil: Sequence[int],
        num_players: int = 5,
        accurate_vote: float = MERLIN_ACCURATE_VOTE,
        pivotal_reject: float = MERLIN_PIVOTAL_REJECT,
        early_accusation: float = MERLIN_EARLY_ACCUSATION,
    ):
        self.owner = owner
        self.evil = set(known_evil) | {owner}
        self.num_players = num_players
        self.accurate_vote = accurate_vote
        self.pivotal_reject = pivotal_reject
        self.early_accusation = early_accusation
        self.candidates = [p for p in range(num_players) if p not in self.evil]
        self.p_merlin: Dict[int, float] = {p: 1.0 / len(self.candidates) for p in self.candidates}

    def update(self, graph: KnowledgeGraph, hammer_attempt: int = 5) -> Dict[int, float]:
        weights = {p: 1.0 for p in self.candidates}
        majority = self.num_players // 2 + 1

        for team in graph.teams.values():
            # Hammer votes carry no signal: the team goes regardless
            if team.approved is None or team.attempt >= hammer_attempt:
                continue
            has_evil = bool(self.evil & set(team.members))
            approvals = sum(team.votes.values())
            for p in self.candidates:
                if p not in team.votes:
                    continue
                approve = team.votes[p]
                accurate = approve != has_evil
                weights[p] *= self.accurate_vote if accurate else 1.0 / self.accurate_vote
                if has_evil and not approve and not team.approved and approvals == majority - 1:
                    weights[p] *= self.pivotal_reject

        # Repeating an accusation is not new evidence: each (accuser, target) counts once
        early = {
            (e.src, e.dst) for e in graph.edges_of(("accused",))
            if e.src in weights and e.dst in self.evil and not self._exposed_before(graph, e.dst, e.seq)
        }
        for src, _ in early:
            weights[src] *= self.early_accusation

        total = sum(weights.values())
        self.p_merlin = {p: w / total for p, w in weights.items()}
        return self.p_merlin

    @staticmethod
    def _exposed_before(graph: KnowledgeGraph, player: int, seq: int) -> bool:
        return any(
            e.seq < seq and graph.teams[e.dst].failed
            for e in graph.edges_of(("member_of",), src=player)
        )

    def top(self) -> int:
        return max(self.candidates, key=lambda p: (self.p_merlin[p], -p))


def spy_id_accurate(p_evil: Dict[int, float], true_evil: set, k: int = 2) -> bool:
    """Are the top-k suspects exactly the true evil players?"""
    top = sorted(p_evil, key=lambda p: (-p_evil[p], p))[:k]
    return set(top) == set(true_evil)


def brier_score(p_evil: Dict[int, float], true_evil: set) -> float:
    """Mean squared error of P(evil) against the true roles. 0.0 is perfect."""
    if not p_evil:
        return 0.0
    return sum((v - (1.0 if p in true_evil else 0.0)) ** 2 for p, v in p_evil.items()) / len(p_evil)
