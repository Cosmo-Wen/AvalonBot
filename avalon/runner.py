"""
Game Orchestrator and Runner for Avalon.

Connects the AvalonEngine, Agent instances, and optional TTS audio synthesizer.
Runs games headlessly for ablation self-play or with voice for live play.
Computes evaluation metrics (Win Rate, Spy-ID accuracy, Brier score, Merlin survival).
"""

import asyncio
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from .engine import AvalonEngine, Role, Phase, ROLE_NAMES
from .agents import Agent, HeuristicAgent
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

    def log(self, msg: str):
        if self.verbose:
            print(msg)

    async def broadcast_event(self, event_type: str, data: Dict[str, Any]):
        for agent in self.agents.values():
            agent.observe_event(event_type, data)

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
                await self.broadcast_event("utterance", {"speaker": p, "text": utterance})

                # Optional voice synthesis
                if self.tts_client:
                    await self.tts_client.speak_seat_utterance(
                        seat=p,
                        text=utterance,
                        turn=turn,
                        round_num=round_num,
                    )

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

            await self.broadcast_event(
                "quest_result",
                {"turn": turn, "team": proposed_team, "success": success, "num_fails": num_fails},
            )

            # Phase 3: Assassination (if triggered)
            if self.engine.phase == Phase.ASSASSINATION and not self.engine.game_over:
                self.log(f"\n[Assassination Phase] Good passed 3 quests! Assassin (Player {assassin_id}) must choose Merlin.")
                target = await self.agents[assassin_id].assassinate()
                self.log(f"Assassin Player {assassin_id} targets Player {target}!")
                self.engine.assassinate(assassin=assassin_id, target=target)

        # 3. Game Over & Metrics
        self.log("\n" + "=" * 50)
        self.log(f"GAME OVER: {self.engine.win_reason}")
        self.log("=" * 50)

        good_spy_id_accuracies: Dict[int, bool] = {}
        good_brier_scores: Dict[int, float] = {}

        for p, agent in self.agents.items():
            if agent.side and agent.belief_graph:
                good_spy_id_accuracies[p] = agent.belief_graph.is_spy_id_accurate(evil_players)
                good_brier_scores[p] = agent.belief_graph.brier_score(evil_players)

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
        )
