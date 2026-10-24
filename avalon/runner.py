"""
Game Orchestrator and Runner for Avalon.

Connects the AvalonEngine, Agent instances, and optional TTS audio synthesizer.
Runs games headlessly for ablation self-play or with voice for live play.
Computes evaluation metrics (Win Rate, Spy-ID accuracy, Brier score, Merlin survival).
"""

import asyncio
import copy
from typing import Callable, Dict, Iterable, List, Optional, Any
from dataclasses import dataclass, field

from .engine import AvalonEngine, Role, Phase, ROLE_NAMES
from .agents import Agent, HeuristicAgent
from .belief_graph import brier_score, spy_id_accurate
from speech.boson_tts import HiggsTTSClient
from speech.audio_pipeline import AudioPipeline
from speech.emotion_mapper import GameStateEmotionMapper, GameStateDelivery


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
    # how each P(evil) update was settled, per Servant: "llm", "llm_retry", or "rule_fallback"
    belief_paths: Dict[int, Dict[str, int]] = field(default_factory=dict)
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
        audio_pipeline: Optional[AudioPipeline] = None,
        verbose: bool = True,
        on_event: Optional[Callable[[str, Dict[str, Any], List[int]], None]] = None,
    ):
        self.agents = agents
        self.engine = AvalonEngine(seed=seed)
        self.tts_client = tts_client
        self.audio_pipeline = audio_pipeline
        self.verbose = verbose
        self.last_quest_result: Optional[Dict[str, Any]] = None
        self.quest_results: List[bool] = []
        self.seq = 0
        # Observer for logging (e.g. the arena harness): sees every event with its recipients,
        # plus private ones no player observes (quest cards, the assassination).
        self.on_event = on_event

    def log(self, msg: str):
        if self.verbose:
            print(msg)

    async def broadcast_event(self, event_type: str, data: Dict[str, Any]):
        await self.deliver_event(event_type, data, self.agents.keys())

    async def deliver_event(self, event_type: str, data: Dict[str, Any], recipients: Iterable[int]):
        """Gives each recipient its own copy of the event, stamped with the next global seq."""
        self.seq += 1
        stamped = dict(data, seq=self.seq)
        recipients = list(recipients)
        for p in recipients:
            self.agents[p].observe_event(event_type, copy.deepcopy(stamped))
        if self.on_event is not None:
            self.on_event(event_type, copy.deepcopy(stamped), recipients)

    def record_private(self, event_type: str, data: Dict[str, Any]) -> None:
        """Reports an event that no player observes to the observer only."""
        if self.on_event is not None:
            self.on_event(event_type, copy.deepcopy(data), [])

    def _is_human(self, seat: int) -> bool:
        """Checks if the player at `seat` is a human participant."""
        agent = self.agents.get(seat)
        if agent is None:
            return False
        return (
            getattr(agent, "is_human", False)
            or getattr(agent, "condition", None) == "human"
            or agent.__class__.__name__ == "HumanVoiceAgent"
        )

    @staticmethod
    def _format_team_names(team: List[int]) -> str:
        """Formats player IDs into a clean English sentence list (e.g. 'Player 0 and Player 1')."""
        names = [f"Player {p}" for p in team]
        if len(names) == 1:
            return names[0]
        elif len(names) == 2:
            return f"{names[0]} and {names[1]}"
        else:
            return ", ".join(names[:-1]) + f", and {names[-1]}"

    async def _narrate(
        self,
        text: str,
        tag: str,
        turn: Optional[int] = None,
        round_num: Optional[int] = None,
        emotion: str = "contemplation",
        style: Optional[str] = None,
        prosody: Optional[List[str]] = None,
    ):
        """Broadcasts, logs, and speaks game master narration through Higgs TTS."""
        self.log(f"[Narrator]: \"{text}\"")
        if self.audio_pipeline:
            self.audio_pipeline.enqueue_narrator(
                text=text,
                turn=turn if turn is not None else 0,
                round_num=round_num if round_num is not None else 0,
                tag=tag,
                emotion=emotion,
                style=style,
                prosody=prosody,
            )
            await self.audio_pipeline.wait_until_idle()
        elif self.tts_client:
            await self.tts_client.speak_narrator(
                text=text,
                tag=tag,
                turn=turn,
                round_num=round_num,
                emotion=emotion,
                style=style,
                prosody=prosody,
            )

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
        self.last_quest_result = None
        self.quest_results = []
        self.seq = 0

        if self.audio_pipeline:
            await self.audio_pipeline.start()

        try:
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
                # One discussion per quest, before its first proposal (every condition): later proposals
                # for the same quest go straight to the vote. Roughly halves the calls per game.
                discussion_order = [leader] + [(leader + i) % 5 for i in range(1, 5)] if round_num == 0 else []
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

                    # Calculate dynamic vocal delivery based on game state
                    delivery = GameStateEmotionMapper.get_delivery_for_utterance(
                        seat=p,
                        role=agent.role,
                        turn=turn,
                        round_num=round_num,
                        last_quest_result=self.last_quest_result,
                        quest_results=self.quest_results,
                        is_hammer_round=(round_num >= 4),
                        recent_rejections=round_num,
                    )

                    # Audio synthesis / playback (skip for human player so bot doesn't repeat what human said)
                    if not self._is_human(p):
                        if self.audio_pipeline:
                            self.audio_pipeline.enqueue_turn(
                                seat=p,
                                text=utterance,
                                turn=turn,
                                round_num=round_num,
                                delivery=delivery,
                            )
                        elif self.tts_client:
                            await self.tts_client.speak_seat_utterance(
                                seat=p,
                                text=utterance,
                                turn=turn,
                                round_num=round_num,
                                style=delivery.style,
                                emotion=delivery.emotion,
                                prosody=delivery.prosody,
                                sfx=delivery.sfx,
                            )

                # If pipelined, let utterances play out before leader finalizes action
                if self.audio_pipeline:
                    await self.audio_pipeline.wait_until_idle()

                # Each player reads the discussion into its own memory before the proposal
                if discussion_order:
                    await asyncio.gather(*(a.after_discussion(turn, round_num) for a in self.agents.values()))

                # Leader proposes team
                proposed_team = await self.agents[leader].propose_team(turn=turn, team_size=req_team_size)
                self.log(f"\n[Action] Leader Player {leader} proposes team: {proposed_team}")
                self.engine.choose_team(leader, proposed_team)
                await self.broadcast_event(
                    "team_proposed",
                    {"turn": turn, "round_num": round_num, "leader": leader, "team": proposed_team},
                )

                team_names = self._format_team_names(proposed_team)

                # Leader bot announces team proposal out loud (skip if human player)
                if not self._is_human(leader):
                    if round_num >= 4:
                        leader_speech = (
                            f"Attention everyone. This is our hammer round. For Quest {turn + 1}, "
                            f"I propose {team_names}. We must approve this mission, or Evil wins."
                        )
                    elif round_num > 0:
                        leader_speech = (
                            f"Following our previous vote, I have revised the plan. For Quest {turn + 1}, "
                            f"I propose {team_names}. I ask for your trust."
                        )
                    else:
                        leader_speech = (
                            f"For Quest {turn + 1}, I propose {team_names}. "
                            f"I believe this team will lead Camelot to victory."
                        )

                    self.log(f"Leader Player {leader} (Spoken): \"{leader_speech}\"")

                    leader_agent = self.agents[leader]
                    leader_delivery = GameStateEmotionMapper.get_delivery_for_utterance(
                        seat=leader,
                        role=leader_agent.role,
                        turn=turn,
                        round_num=round_num,
                        last_quest_result=self.last_quest_result,
                        quest_results=self.quest_results,
                        is_hammer_round=(round_num >= 4),
                        recent_rejections=round_num,
                    )

                    if self.audio_pipeline:
                        self.audio_pipeline.enqueue_turn(
                            seat=leader,
                            text=leader_speech,
                            turn=turn,
                            round_num=round_num,
                            delivery=leader_delivery,
                            tag="proposal",
                        )
                        await self.audio_pipeline.wait_until_idle()
                    elif self.tts_client:
                        await self.tts_client.speak_seat_utterance(
                            seat=leader,
                            text=leader_speech,
                            turn=turn,
                            round_num=round_num,
                            style=leader_delivery.style,
                            emotion=leader_delivery.emotion,
                            prosody=leader_delivery.prosody,
                            sfx=leader_delivery.sfx,
                            tag="proposal",
                        )

                # Narrator announces team proposal and calls for vote
                narrator_proposal = (
                    f"Leader Player {leader} has proposed {team_names} for Quest {turn + 1}. "
                    f"All players, cast your votes to approve or reject."
                )
                await self._narrate(
                    text=narrator_proposal,
                    tag="proposal",
                    turn=turn,
                    round_num=round_num,
                    emotion="contemplation",
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

                # Narrator announces team selection decision
                num_approvals = sum(1 for v in votes.values() if v)
                num_rejections = len(votes) - num_approvals
                if approved:
                    narrator_vote = (
                        f"The council has voted. With {num_approvals} approvals and {num_rejections} rejections, "
                        f"the proposed team is APPROVED. The chosen knights will embark on Quest {turn + 1}."
                    )
                    vote_emotion = "elation"
                else:
                    if round_num >= 4:
                        narrator_vote = (
                            f"With {num_approvals} approvals and {num_rejections} rejections, "
                            f"the proposed team is REJECTED. Five proposals have failed, and Camelot falls to Evil!"
                        )
                        vote_emotion = "fear"
                    else:
                        next_leader = (leader + 1) % 5
                        narrator_vote = (
                            f"With {num_approvals} approvals and {num_rejections} rejections, "
                            f"the proposed team is REJECTED. Leadership passes to Player {next_leader}."
                        )
                        vote_emotion = "contemplation"

                await self._narrate(
                    text=narrator_vote,
                    tag="vote_result",
                    turn=turn,
                    round_num=round_num,
                    emotion=vote_emotion,
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
                self.record_private("quest_cards", {"turn": turn, "team": proposed_team, "cards": dict(quest_votes)})

                self.last_quest_result = {
                    "turn": turn,
                    "team": proposed_team,
                    "success": success,
                    "num_fails": num_fails,
                }
                self.quest_results.append(success)

                await self.broadcast_event(
                    "quest_result",
                    {"turn": turn, "round_num": round_num, "team": proposed_team, "success": success, "num_fails": num_fails},
                )

                # Narrator announces quest outcome
                if success:
                    narrator_quest = f"Quest {turn + 1} has SUCCEEDED! Arthur's kingdom stands strong."
                    quest_emotion = "elation"
                else:
                    fail_word = "betrayal" if num_fails == 1 else "betrayals"
                    narrator_quest = f"Quest {turn + 1} has FAILED with {num_fails} {fail_word}! Treachery strikes Camelot."
                    quest_emotion = "fear"

                await self._narrate(
                    text=narrator_quest,
                    tag="quest_outcome",
                    turn=turn,
                    round_num=round_num,
                    emotion=quest_emotion,
                )

                # Phase 3: Assassination (if triggered)
                if self.engine.phase == Phase.ASSASSINATION and not self.engine.game_over:
                    self.log(f"\n[Assassination Phase] Good passed 3 quests! Assassin (Player {assassin_id}) must choose Merlin.")
                    await self._narrate(
                        text=f"The forces of Good have won three quests! But the Assassin, Player {assassin_id}, now steps forward to identify and eliminate Merlin.",
                        tag="assassination_phase",
                        turn=turn,
                        round_num=round_num,
                        emotion="fear",
                    )

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

                    assassin_memory = getattr(self.agents[assassin_id], "memory", None)
                    if assassin_memory is not None and getattr(assassin_memory, "merlin", None) is not None:
                        assassin_p_merlin = dict(assassin_memory.merlin.p_merlin)
                        shown = ", ".join(f"P{p}: {v:.2f}" for p, v in sorted(assassin_p_merlin.items()))
                        self.log(f"[Assassin's P(Merlin)] {shown}")

                    target = await self.agents[assassin_id].assassinate()
                    self.log(f"Assassin Player {assassin_id} targets Player {target}!")
                    self.engine.assassinate(assassin=assassin_id, target=target)
                    self.record_private("assassination", {"assassin": assassin_id, "target": target,
                                                          "hit_merlin": target == merlin_id})
        finally:
            if self.audio_pipeline:
                await self.audio_pipeline.stop()

        # 3. Game Over & Metrics
        self.log("\n" + "=" * 50)
        self.log(f"GAME OVER: {self.engine.win_reason}")
        self.log("=" * 50)

        await self._narrate(
            text=f"The battle for Avalon concludes. {self.engine.win_reason}",
            tag="game_over",
            emotion="elation" if self.engine.good_victory else "fear",
        )

        good_spy_id_accuracies: Dict[int, bool] = {}
        good_brier_scores: Dict[int, float] = {}
        final_p_evil: Dict[int, Dict[int, float]] = {}
        belief_fallbacks: Dict[int, int] = {}
        constraint_resets: Dict[int, int] = {}
        belief_paths: Dict[int, Dict[str, int]] = {}

        # Only Loyal Servants hold P(evil)
        for p, agent in self.agents.items():
            p_evil = await agent.final_beliefs()
            if p_evil is None:
                continue
            final_p_evil[p] = p_evil
            good_spy_id_accuracies[p] = spy_id_accurate(p_evil, evil_players)
            good_brier_scores[p] = brier_score(p_evil, evil_players)
            agent_mem = getattr(agent, "memory", None)
            if agent_mem is not None:
                belief_fallbacks[p] = getattr(agent_mem, "belief_fallbacks", 0)
                constraint_resets[p] = getattr(agent_mem, "constraint_resets", 0)
                belief_paths[p] = dict(getattr(agent_mem, "belief_paths", {}))

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
            belief_paths=belief_paths,
            assassin_p_merlin=assassin_p_merlin,
        )
