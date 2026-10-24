"""
Game Orchestrator and Runner for Avalon.

Connects the AvalonEngine, Agent instances, and optional TTS audio synthesizer.
Runs games headlessly for ablation self-play or with voice for live play.
Computes evaluation metrics (Win Rate, Spy-ID accuracy, Brier score, Merlin survival).
"""

import asyncio
import copy
from typing import Dict, Iterable, List, Optional, Any
from dataclasses import dataclass, field

from .engine import AvalonEngine, Role, Phase, ROLE_NAMES
from .agents import Agent, HeuristicAgent
from .belief_graph import brier_score, spy_id_accurate
from speech.boson_tts import HiggsTTSClient


@dataclass
class GameMetrics:
    good_victory: bool
    win_reason: str
    total_turns: int
    merlin_id: int
    assassin_id: int
    assassination_target: Optional[int]
    merlin_survived: bool
    good_spy_id_accuracies: Dict[int, bool] = field(default_factory=dict)
    good_brier_scores: Dict[int, float] = field(default_factory=dict)
    final_p_evil: Dict[int, Dict[int, float]] = field(default_factory=dict)
    belief_fallbacks: Dict[int, int] = field(default_factory=dict)
    constraint_resets: Dict[int, int] = field(default_factory=dict)
    assassin_p_merlin: Optional[Dict[int, float]] = None


class AvalonGameRunner:
    """
    Asynchronous event-driven orchestrator for 5-Player Avalon.
    """

    def __init__(
        self,
        agents: Dict[int, Agent],
        seed: Optional[int] = None,
        tts_client: Optional[HiggsTTSClient] = None,
        verbose: bool = True,
    ):
        self.agents = agents
        self.engine = AvalonEngine(seed=seed)
        self.tts_client = tts_client
        self.verbose = verbose
        self.seq = 0

    def log(self, msg: str):
        if self.verbose:
            print(msg)

    async def broadcast_event(self, event_type: str, data: Dict[str, Any]):
        await self.deliver_event(event_type, data, self.agents.keys())

    async def deliver_event(self, event_type: str, data: Dict[str, Any], recipients: Iterable[int]):
        """Gives each recipient its own copy of the event, stamped with the next global seq."""
        self.seq += 1
        stamped = dict(data, seq=self.seq)
        for p in recipients:
            self.agents[p].observe_event(event_type, copy.deepcopy(stamped))

    async def run_game(
        self,
        preset_roles: Optional[Dict[int, Role]] = None,
        preset_leader: Optional[int] = None,
    ) -> GameMetrics:
        """
        Executes an entire game of Avalon from start to finish.
        """
        # 1. Reset engine and initialize roles
        roles = self.engine.reset(preset_roles=preset_roles, preset_leader=preset_leader)
        self.seq = 0

        self.log("\n" + "=" * 50)
        self.log("Starting New 5-Player Avalon Game")
        self.log("=" * 50)

        # Distribute private info to agents
        for p, role in roles.items():
            self.agents[p].role = role
            self.agents[p].side = self.engine.player_sides[p]
            p_info = self.engine.get_private_info(p)
            self.agents[p].set_private_info(p_info)
            self.log(f"Player {p}: {ROLE_NAMES[role]} ({'Good' if p_info['side'] else 'Evil'})")

        merlin_id = self.engine.get_merlin()
        assassin_id = self.engine.get_assassin()
        evil_players = set(self.engine.get_evil_players())
        assassin_p_merlin: Optional[Dict[int, float]] = None

        # 2. Game Loop
        while not self.engine.game_over:
            turn = self.engine.turn
            round_num = self.engine.round_num
            leader = self.engine.leader
            req_team_size = self.engine.get_required_team_size()

            self.log(f"\n--- Quest {turn + 1} | Round {round_num + 1} | Leader: Player {leader} ---")

            # Phase 0: Discussion & Proposal
            # Discussion circular order: leader first, then others
            discussion_order = [leader] + [(leader + i) % 5 for i in range(1, 5)]
            for p in discussion_order:
                agent = self.agents[p]
                utterance = await agent.team_discussion(
                    turn=turn,
                    round_num=round_num,
                    leader=leader,
                    team_size=req_team_size,
                )
                self.log(f"Player {p}: \"{utterance}\"")
                await self.broadcast_event(
                    "utterance",
                    {"turn": turn, "round_num": round_num, "speaker": p, "text": utterance},
                )

                # Optional voice synthesis
                if self.tts_client:
                    await self.tts_client.speak_seat_utterance(
                        seat=p,
                        text=utterance,
                        turn=turn,
                        round_num=round_num,
                    )

            # Each player reads the discussion into its own memory before the proposal
            await asyncio.gather(*(a.after_discussion(turn, round_num) for a in self.agents.values()))

            # Leader proposes team
            proposed_team = await self.agents[leader].propose_team(turn=turn, team_size=req_team_size)
            self.log(f"\n[Action] Leader Player {leader} proposes team: {proposed_team}")
            self.engine.choose_team(leader, proposed_team)
            await self.broadcast_event(
                "team_proposed",
                {"turn": turn, "round_num": round_num, "leader": leader, "team": proposed_team},
            )

            # Phase 1: Team Voting
            votes: Dict[int, bool] = {}
            for p, agent in self.agents.items():
                votes[p] = await agent.vote_on_team(
                    turn=turn,
                    round_num=round_num,
                    leader=leader,
                    team=proposed_team,
                )

            next_phase, game_over, approved = self.engine.vote_on_team(votes)
            vote_summary = ", ".join(f"P{p}:{'Y' if v else 'N'}" for p, v in votes.items())
            self.log(f"[Vote Result] Team {'APPROVED' if approved else 'REJECTED'} ({vote_summary})")

            await self.broadcast_event(
                "team_vote_result",
                {
                    "turn": turn,
                    "round_num": round_num,
                    "leader": leader,
                    "team": proposed_team,
                    "votes": votes,
                    "approved": approved,
                },
            )

            if not approved:
                continue  # Loop to next proposal round

            # Phase 2: Quest Voting
            quest_votes: Dict[int, bool] = {}
            for p in proposed_team:
                quest_votes[p] = await self.agents[p].vote_on_quest(turn=turn, team=proposed_team)

            next_phase, game_over, success, num_fails = self.engine.vote_on_quest(quest_votes)
            self.log(f"[Quest Outcome] Quest {turn + 1} {'SUCCEEDED' if success else 'FAILED'} ({num_fails} fail votes)")

            # Each card is known only to the player who played it
            for p, card in quest_votes.items():
                self.agents[p].record_own_quest_card(turn, card)

            await self.broadcast_event(
                "quest_result",
                {"turn": turn, "round_num": round_num, "team": proposed_team, "success": success, "num_fails": num_fails},
            )

            # Phase 3: Assassination (if triggered)
            if self.engine.phase == Phase.ASSASSINATION and not self.engine.game_over:
                self.log(f"\n[Assassination Phase] Good passed 3 quests! Assassin (Player {assassin_id}) must choose Merlin.")

                # Evil-only discussion: delivered to the evil players and nobody else
                evil_order = sorted(evil_players, key=lambda p: p == assassin_id)
                for p in evil_order:
                    line = await self.agents[p].evil_discussion(turn=self.engine.turn)
                    if line:
                        self.log(f"[Evil only] Player {p}: \"{line}\"")
                        await self.deliver_event(
                            "evil_chat",
                            {"turn": self.engine.turn, "round_num": 0, "speaker": p, "text": line},
                            recipients=evil_order,
                        )

                assassin_memory = self.agents[assassin_id].memory
                if assassin_memory is not None and assassin_memory.merlin is not None:
                    assassin_p_merlin = dict(assassin_memory.merlin.p_merlin)
                    shown = ", ".join(f"P{p}: {v:.2f}" for p, v in sorted(assassin_p_merlin.items()))
                    self.log(f"[Assassin's P(Merlin)] {shown}")

                target = await self.agents[assassin_id].assassinate()
                self.log(f"Assassin Player {assassin_id} targets Player {target}!")
                self.engine.assassinate(assassin=assassin_id, target=target)

        # 3. Game Over & Metrics
        self.log("\n" + "=" * 50)
        self.log(f"GAME OVER: {self.engine.win_reason}")
        self.log("=" * 50)

        good_spy_id_accuracies: Dict[int, bool] = {}
        good_brier_scores: Dict[int, float] = {}
        final_p_evil: Dict[int, Dict[int, float]] = {}
        belief_fallbacks: Dict[int, int] = {}
        constraint_resets: Dict[int, int] = {}

        # Only Loyal Servants hold P(evil)
        for p, agent in self.agents.items():
            p_evil = await agent.final_beliefs()
            if p_evil is None:
                continue
            final_p_evil[p] = p_evil
            good_spy_id_accuracies[p] = spy_id_accurate(p_evil, evil_players)
            good_brier_scores[p] = brier_score(p_evil, evil_players)
            belief_fallbacks[p] = agent.memory.belief_fallbacks
            constraint_resets[p] = agent.memory.constraint_resets

        merlin_survived = (
            self.engine.good_victory is True
            and self.engine.assassination_target is not None
            and self.engine.assassination_target != merlin_id
        )

        return GameMetrics(
            good_victory=bool(self.engine.good_victory),
            win_reason=self.engine.win_reason,
            total_turns=self.engine.turn,
            merlin_id=merlin_id,
            assassin_id=assassin_id,
            assassination_target=self.engine.assassination_target,
            merlin_survived=merlin_survived,
            good_spy_id_accuracies=good_spy_id_accuracies,
            good_brier_scores=good_brier_scores,
            final_p_evil=final_p_evil,
            belief_fallbacks=belief_fallbacks,
            constraint_resets=constraint_resets,
            assassin_p_merlin=assassin_p_merlin,
        )
