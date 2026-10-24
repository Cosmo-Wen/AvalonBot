"""
Per-player memory (see MEMORY_MODEL.md).

Layer 1, observation log: what this player saw or heard. Written only from delivered events.
Layer 2, private knowledge: role, who it saw at the start, its own quest cards.
Layer 3, own reasoning: knowledge graph, beliefs, notes, and self edges.

Nothing another player thought ever enters this memory.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .belief_graph import (
    MAX_NOTE_WORDS,
    TALK_EDGES,
    Edge,
    KnowledgeGraph,
    MerlinBelief,
    PairBelief,
    clip_words,
    team_label,
)
from .engine import ROLE_NAMES, Role


LOG_KINDS = ("utterance", "proposal", "team_vote", "quest_result", "evil_chat")

EVENT_KINDS = {
    "utterance": "utterance",
    "team_proposed": "proposal",
    "team_vote_result": "team_vote",
    "quest_result": "quest_result",
    "evil_chat": "evil_chat",
}

_TTS_TAG = re.compile(r"<\|[^|]*\|>")


def strip_tts_tags(text: str) -> str:
    return " ".join(_TTS_TAG.sub(" ", text).split())


@dataclass(frozen=True)
class LogEntry:
    seq: int
    kind: str
    quest: int
    attempt: int
    speaker: Optional[int] = None
    text: str = ""
    leader: Optional[int] = None
    members: Tuple[int, ...] = ()
    votes: Tuple[Tuple[int, bool], ...] = ()
    approved: Optional[bool] = None
    fails: Optional[int] = None
    success: Optional[bool] = None

    @property
    def label(self) -> str:
        return team_label(self.quest, self.attempt)

    def involves(self, player: int) -> bool:
        return (
            self.speaker == player
            or self.leader == player
            or player in self.members
            or any(p == player for p, _ in self.votes)
        )

    def render(self) -> str:
        team = "{" + ",".join(str(p) for p in self.members) + "}"
        if self.kind == "utterance":
            return f'#{self.seq} [{self.label}] P{self.speaker}: "{self.text}"'
        if self.kind == "proposal":
            return f"#{self.seq} [{self.label}] P{self.leader} proposed {team}"
        if self.kind == "team_vote":
            votes = ", ".join(f"P{p}:{'Y' if v else 'N'}" for p, v in self.votes)
            return f"#{self.seq} [{self.label}] Team {'APPROVED' if self.approved else 'REJECTED'} ({votes})"
        if self.kind == "quest_result":
            outcome = "SUCCEEDED" if self.success else f"FAILED with {self.fails} fail(s)"
            return f"#{self.seq} [{self.label}] Quest {self.quest} {outcome}, team {team}"
        return f'#{self.seq} [evil only] P{self.speaker}: "{self.text}"'


@dataclass
class PrivateKnowledge:
    role: Role
    side: bool
    seen_evil: Tuple[int, ...]
    my_quest_cards: Dict[int, bool] = field(default_factory=dict)

    @property
    def role_name(self) -> str:
        return ROLE_NAMES[self.role]


class PlayerMemory:
    """
    One player's private memory. Each agent owns exactly one; nothing is shared.
    """

    def __init__(
        self,
        owner: int,
        private_info: Dict[str, Any],
        num_players: int = 5,
        belief_mode: str = "rule",
        merlin_graph: bool = False,
    ):
        self.owner = owner
        self.num_players = num_players
        self.private = PrivateKnowledge(
            role=private_info["role"],
            side=bool(private_info["side"]),
            seen_evil=tuple(private_info.get("seen_evil", [])),
        )
        self.log: List[LogEntry] = []
        self._by_seq: Dict[int, LogEntry] = {}
        self.graph = KnowledgeGraph(owner, num_players)

        # Only Loyal Servants hold P(evil). "llm": set by the extraction call (condition B).
        # "rule": computed by the Condition C rule (C, and kept silently in A).
        self.beliefs: Optional[PairBelief] = (
            PairBelief(owner, num_players) if self.private.role == Role.LOYAL_SERVANT else None
        )
        self.belief_mode = belief_mode

        # Evil players' P(Merlin), demo only. Off in the ablation so evil is identical across conditions.
        self.merlin: Optional[MerlinBelief] = (
            MerlinBelief(owner, self.private.seen_evil, num_players)
            if merlin_graph and not self.private.side else None
        )
        self.notes: Dict[int, str] = {}
        self.free_notes: List[str] = []
        self.belief_fallbacks = 0
        # how each LLM P(evil) update was settled: "llm", "llm_retry", or "rule_fallback"
        self.belief_paths: Dict[str, int] = {}
        self.constraint_resets = 0

    # Layer 1: observation log

    def observe(self, event_type: str, data: Dict[str, Any]) -> Optional[LogEntry]:
        kind = EVENT_KINDS.get(event_type)
        if kind is None:
            return None
        seq = int(data["seq"])
        if seq in self._by_seq:
            raise ValueError(f"Player {self.owner} already has log entry #{seq}")
        if kind == "evil_chat" and self.private.side:
            raise ValueError(f"Evil-only chat delivered to good player {self.owner}")

        quest = int(data.get("turn", 0)) + 1
        attempt = int(data.get("round_num", 0)) + 1
        votes = data.get("votes") or {}
        entry = LogEntry(
            seq=seq,
            kind=kind,
            quest=quest,
            attempt=attempt,
            speaker=data.get("speaker"),
            text=strip_tts_tags(data.get("text", "")),
            leader=data.get("leader"),
            members=tuple(sorted(data.get("team", []))),
            votes=tuple(sorted((int(p), bool(v)) for p, v in votes.items())),
            approved=data.get("approved"),
            fails=data.get("num_fails"),
            success=data.get("success"),
        )
        self.log.append(entry)
        self._by_seq[seq] = entry
        self._update_graph(entry)
        if kind in ("team_vote", "quest_result"):
            self.update_merlin()
        return entry

    def update_merlin(self) -> None:
        if self.merlin is not None:
            self.merlin.update(self.graph)

    def _update_graph(self, e: LogEntry) -> None:
        if e.kind == "utterance" and e.speaker == self.owner:
            self.graph.add_said(e.seq, e.quest, e.attempt, e.text)
        elif e.kind == "proposal":
            self.graph.add_proposal(e.seq, e.quest, e.attempt, e.leader, e.members)
        elif e.kind == "team_vote":
            self.graph.add_team_vote(e.seq, e.quest, e.attempt, dict(e.votes), bool(e.approved))
        elif e.kind == "quest_result":
            team = self.graph.add_quest_result(e.seq, e.quest, e.attempt, int(e.fails or 0), bool(e.success))
            own_fails = 1 if self.private.my_quest_cards.get(e.quest) is False else 0
            if own_fails and team.failed:
                self.graph.own_fails[team.label] = own_fails
            others_evil = (team.fails or 0) - own_fails
            if self.beliefs is not None and team.failed and others_evil > 0:
                self.beliefs.add_failed_quest(team.members, others_evil, team.votes)
                if self.belief_mode != "llm":
                    self.beliefs.set_rule()
                elif self.beliefs.validate(self.beliefs.p_evil):
                    self.beliefs.set_rule()
                    self.constraint_resets += 1

    # Layer 2: private knowledge

    def record_quest_card(self, quest: int, passed: bool) -> None:
        self.private.my_quest_cards[quest] = passed

    # Layer 3: own reasoning

    def record_reason(self, quest: int, attempt: int, action: str, reason: str) -> Optional[Edge]:
        """Saves why this player proposed or voted. Cites the latest entry it had seen."""
        if not reason or not self.log:
            return None
        seq = self.log[-1].seq
        return self.graph.add_reasoned(seq, quest, attempt, action, team_label(quest, attempt), reason)

    def add_talk_edges(self, raw_edges: Sequence[Dict[str, Any]]) -> Tuple[List[Edge], int]:
        """
        Adds talk edges proposed by this player's own extraction call.
        Drops any edge whose sources are not utterances by `from` in this player's log.
        Returns (added edges, number dropped).
        """
        added: List[Edge] = []
        dropped = 0
        for raw in raw_edges or []:
            edge = self._parse_talk_edge(raw)
            if edge is None:
                dropped += 1
            else:
                added.append(edge)
        if added:
            self.update_merlin()
        return added, dropped

    def _parse_talk_edge(self, raw: Dict[str, Any]) -> Optional[Edge]:
        try:
            type_ = str(raw["type"])
            src = int(raw["from"])
            sources = raw.get("sources") or [raw["seq"]]
            sources = [int(s) for s in sources]
        except (KeyError, TypeError, ValueError):
            return None
        if type_ not in TALK_EDGES or not sources:
            return None

        entries = [self._by_seq.get(s) for s in sources]
        if any(e is None or e.kind not in ("utterance", "evil_chat") or e.speaker != src for e in entries):
            return None
        latest = max(entries, key=lambda e: e.seq)

        dst: Any = raw.get("to")
        role = ""
        if type_ in ("accused", "defended"):
            try:
                dst = int(dst)
            except (TypeError, ValueError):
                return None
        elif type_ == "claimed_role":
            role = str(raw.get("role", "")).strip()
            if role not in ROLE_NAMES.values():
                return None
            dst = src
        else:
            dst = str(dst)

        return self.graph.add_talk_edge(
            type_, src, dst, latest.seq, latest.quest, latest.attempt, sources,
            quote=str(raw.get("quote", "")),
            role=role,
        )

    def set_notes(self, notes: Dict[Any, Any]) -> None:
        for key, text in (notes or {}).items():
            try:
                player = int(key)
            except (TypeError, ValueError):
                continue
            if player != self.owner and 0 <= player < self.num_players and text:
                self.notes[player] = clip_words(str(text), MAX_NOTE_WORDS)

    def add_free_note(self, text: str) -> None:
        if text and text.strip():
            self.free_notes.append(" ".join(text.split()))

    def record_belief_path(self, path: str) -> None:
        self.belief_paths[path] = self.belief_paths.get(path, 0) + 1

    def apply_llm_beliefs(self, raw: Dict[Any, Any], check_evidence: bool = False) -> List[str]:
        """Checks and applies P(evil) proposed by the LLM. Returns errors (empty on success)."""
        if self.beliefs is None:
            return ["this player keeps no P(evil)"]
        try:
            p_evil = {int(k): float(v) for k, v in (raw or {}).items()}
        except (TypeError, ValueError):
            return ["p_evil must map player ids to numbers"]
        if check_evidence:
            errors = self.beliefs.validate(p_evil) or self.beliefs.evidence_errors(p_evil)
            if errors:
                return errors
        return self.beliefs.set_llm(p_evil)

    def fall_back_to_rule(self) -> None:
        if self.beliefs is not None:
            self.beliefs.set_rule()
            self.belief_fallbacks += 1

    # Recall (exact lookup over this player's own memory)

    def recall(
        self,
        player: Optional[int] = None,
        from_seq: Optional[int] = None,
        to_seq: Optional[int] = None,
        kinds: Optional[Sequence[str]] = None,
    ) -> List[LogEntry]:
        return [
            e for e in self.log
            if (player is None or e.involves(player))
            and (from_seq is None or e.seq >= from_seq)
            and (to_seq is None or e.seq <= to_seq)
            and (not kinds or e.kind in kinds)
        ]

    def quote(self, seq: int) -> Optional[LogEntry]:
        return self._by_seq.get(seq)

    def evidence(self, player: int) -> List[Edge]:
        return self.graph.evidence(player)

    def my_record(self, quest: Optional[int] = None) -> Dict[str, Any]:
        edges = [
            e for e in self.graph.edges_of(("i_said", "i_reasoned"), src=self.owner)
            if quest is None or e.quest == quest
        ]
        cards = {q: c for q, c in self.private.my_quest_cards.items() if quest is None or q == quest}
        return {"edges": edges, "quest_cards": cards}

    def run_tool(self, name: str, args: Dict[str, Any]) -> str:
        """Executes a recall tool call and returns its text result for the LLM."""
        try:
            if name == "recall":
                entries = self.recall(
                    player=args.get("player"),
                    from_seq=args.get("from_seq"),
                    to_seq=args.get("to_seq"),
                    kinds=args.get("kinds"),
                )
                return self.render_log(entries) or "No matching entries."
            if name == "quote":
                entry = self.quote(int(args["seq"]))
                return entry.render() if entry else f"You have no entry #{args['seq']}."
            if name == "evidence":
                edges = self.evidence(int(args["player"]))
                return "\n".join(_render_edge(e) for e in edges) or "No evidence recorded."
            if name == "my_record":
                record = self.my_record(args.get("quest"))
                lines = [_render_edge(e) for e in record["edges"]]
                lines += [f"Quest {q}: you played {'Success' if c else 'Fail'}" for q, c in sorted(record["quest_cards"].items())]
                return "\n".join(lines) or "Nothing recorded yet."
        except (KeyError, TypeError, ValueError) as exc:
            return f"Invalid arguments for {name}: {exc}"
        return f"Unknown tool {name}."

    # Rendering for this player's own prompt

    def render_log(self, entries: Optional[Sequence[LogEntry]] = None) -> str:
        return "\n".join(e.render() for e in (self.log if entries is None else entries))

    def render_private(self) -> str:
        lines = [f"You are Player {self.owner}, {self.private.role_name} ({'Good' if self.private.side else 'Evil'})."]
        if self.private.seen_evil:
            who = ", ".join(f"P{p}" for p in self.private.seen_evil)
            if self.private.role == Role.MERLIN:
                lines.append(f"You saw at the start that {who} are evil.")
            else:
                lines.append(f"Your evil partner: {who}.")
        for q, card in sorted(self.private.my_quest_cards.items()):
            lines.append(f"Quest {q}: you played {'Success' if card else 'Fail'}.")
        return "\n".join(lines)

    def render_table(self) -> str:
        if self.merlin is not None:
            table = self.graph.render_table(self.merlin.p_merlin, belief_name="P(Merlin)")
        else:
            p_evil = self.beliefs.p_evil if self.beliefs is not None else None
            table = self.graph.render_table(p_evil)
        if self.notes:
            notes = "; ".join(f"P{p}: {n}" for p, n in sorted(self.notes.items()))
            table += f"\nYour notes: {notes}"
        return table

    def render_notes(self, recent: int = 5) -> str:
        return "\n".join(f"- {n}" for n in self.free_notes[-recent:])

    # Convenience

    def any_failed_quest(self) -> bool:
        return any(e.kind == "quest_result" and e.success is False for e in self.log)

    def entries_since_quest(self, quest: int) -> List[LogEntry]:
        return [e for e in self.log if e.quest >= quest]

    def discussion_entries(self, quest: int, attempt: int) -> List[LogEntry]:
        return [e for e in self.log if e.kind == "utterance" and e.quest == quest and e.attempt == attempt]

    def all_text(self) -> str:
        """Every string this memory holds. Used by the isolation test."""
        return json.dumps(
            {
                "log": [e.render() for e in self.log],
                "edges": [vars(e) for e in self.graph.edges],
                "notes": self.notes,
                "free_notes": self.free_notes,
            },
            default=str,
        )


def _render_edge(e: Edge) -> str:
    if e.type == "i_said":
        return f'#{e.seq} you said "{e.quote}"'
    if e.type == "i_reasoned":
        return f'#{e.seq} you {e.action} {e.dst}: "{e.reason}"'
    target = f"P{e.dst}" if isinstance(e.dst, int) else e.dst
    extra = f' "{e.quote}"' if e.quote else ""
    if e.type == "claimed_role":
        return f"#{e.seq} P{e.src} claimed {e.role}{extra}"
    return f"#{e.seq} P{e.src} {e.type} {target}{extra} (sources {e.sources})"
