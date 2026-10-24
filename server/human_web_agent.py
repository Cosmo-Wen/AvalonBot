"""
Human Web Agent for Avalon.

Connects a human player in the browser to the AvalonGameRunner via WebSocket.
Prompts the browser UI for:
1. Team discussion statement (typed text or speech)
2. Team proposal selection (when human is leader)
3. Team vote (Approve / Reject)
4. Secret Quest Card (Pass / Fail) - completely private and silent in the UI
5. Assassination target (when human is the Assassin)
"""

import asyncio
from typing import Dict, List, Optional, Any
from avalon.engine import Role, ROLE_NAMES
from avalon.agents import Agent


class HumanWebAgent(Agent):
    """
    Human player agent interacting asynchronously with the Web UI over WebSocket.
    """

    def __init__(self, player_id: int, session: Any, role: Role = Role.LOYAL_SERVANT):
        super().__init__(player_id=player_id, role=role, condition="human")
        self.session = session
        self.is_human = True
        self.pending_future: Optional[asyncio.Future] = None
        self.current_action: Optional[str] = None
        self.speak_audio = True

    def set_private_info(self, info: Dict[str, Any]):
        super().set_private_info(info)
        # Notify the browser of the human player's private identity
        asyncio.create_task(
            self.session.send(
                "human_role",
                {
                    "seat": self.player_id,
                    "role": ROLE_NAMES.get(self.role, str(self.role)),
                    "side": "good" if self.side else "evil",
                    "seen_players": info.get("seen_players", []),
                    "evil_players": info.get("evil_players", []),
                },
            )
        )

    def resolve_action(self, action: str, data: Dict[str, Any]):
        """Called by ws_server when a human_action_response arrives from the browser."""
        if self.pending_future and not self.pending_future.done():
            self.pending_future.set_result(data)

    async def team_discussion(self, turn: int, round_num: int, leader: int, team_size: int) -> str:
        if hasattr(self.session, "wait_speech_idle"):
            await self.session.wait_speech_idle()
        prompt_data = {
            "action": "discussion",
            "seat": self.player_id,
            "turn": turn,
            "round_num": round_num,
            "leader": leader,
            "team_size": team_size,
        }
        await self.session.send("human_prompt", prompt_data)
        self.pending_future = asyncio.get_running_loop().create_future()
        self.current_action = "discussion"
        try:
            res = await self.pending_future
            text = str(res.get("text", "")).strip()
            self.speak_audio = bool(res.get("speak_audio", True))
            return text or f"I am a loyal servant of Arthur and want what is best for the realm."
        finally:
            self.pending_future = None
            self.current_action = None
            await self.session.send("human_prompt_clear", {"action": "discussion"})

    async def propose_team(self, turn: int, team_size: int) -> List[int]:
        if hasattr(self.session, "wait_speech_idle"):
            await self.session.wait_speech_idle()
        prompt_data = {
            "action": "propose_team",
            "seat": self.player_id,
            "turn": turn,
            "team_size": team_size,
        }
        await self.session.send("human_prompt", prompt_data)
        self.pending_future = asyncio.get_running_loop().create_future()
        self.current_action = "propose_team"
        try:
            res = await self.pending_future
            raw_team = res.get("team", [])
            if isinstance(raw_team, list) and len(raw_team) == team_size:
                return [int(p) for p in raw_team]
            return list(range(team_size))
        finally:
            self.pending_future = None
            self.current_action = None
            await self.session.send("human_prompt_clear", {"action": "propose_team"})

    async def vote_on_team(self, turn: int, round_num: int, leader: int, team: List[int]) -> bool:
        if hasattr(self.session, "wait_speech_idle"):
            await self.session.wait_speech_idle()
        prompt_data = {
            "action": "vote_on_team",
            "seat": self.player_id,
            "turn": turn,
            "round_num": round_num,
            "leader": leader,
            "team": team,
        }
        await self.session.send("human_prompt", prompt_data)
        self.pending_future = asyncio.get_running_loop().create_future()
        self.current_action = "vote_on_team"
        try:
            res = await self.pending_future
            return bool(res.get("vote", True))
        finally:
            self.pending_future = None
            self.current_action = None
            await self.session.send("human_prompt_clear", {"action": "vote_on_team"})

    async def vote_on_quest(self, turn: int, team: List[int]) -> bool:
        # In Avalon, Good players MUST submit a Pass card. They cannot sabotage.
        # Evil players can choose Pass or Fail secretly.
        if self.side:
            prompt_data = {
                "action": "vote_on_quest",
                "seat": self.player_id,
                "turn": turn,
                "team": team,
                "can_fail": False,
                "side": "good",
            }
            await self.session.send("human_prompt", prompt_data)
            self.pending_future = asyncio.get_running_loop().create_future()
            self.current_action = "vote_on_quest"
            try:
                # Give user up to 4s to click Confirm Pass, else auto-pass
                await asyncio.wait_for(self.pending_future, timeout=4.0)
            except asyncio.TimeoutError:
                pass
            finally:
                self.pending_future = None
                self.current_action = None
                await self.session.send("human_prompt_clear", {"action": "vote_on_quest"})
            return True

        # Evil: secret choice between Pass and Fail
        prompt_data = {
            "action": "vote_on_quest",
            "seat": self.player_id,
            "turn": turn,
            "team": team,
            "can_fail": True,
            "side": "evil",
        }
        await self.session.send("human_prompt", prompt_data)
        self.pending_future = asyncio.get_running_loop().create_future()
        self.current_action = "vote_on_quest"
        try:
            res = await self.pending_future
            return bool(res.get("vote", True))
        finally:
            self.pending_future = None
            self.current_action = None
            await self.session.send("human_prompt_clear", {"action": "vote_on_quest"})

    async def evil_discussion(self, turn: int) -> str:
        prompt_data = {
            "action": "evil_discussion",
            "seat": self.player_id,
            "turn": turn,
        }
        await self.session.send("human_prompt", prompt_data)
        self.pending_future = asyncio.get_running_loop().create_future()
        self.current_action = "evil_discussion"
        try:
            res = await self.pending_future
            return str(res.get("text", "")).strip() or "I suspect Player 4 is Merlin."
        finally:
            self.pending_future = None
            self.current_action = None
            await self.session.send("human_prompt_clear", {"action": "evil_discussion"})

    async def assassinate(self) -> int:
        candidates = [p for p in range(self.num_players) if p != self.player_id]
        prompt_data = {
            "action": "assassinate",
            "seat": self.player_id,
            "candidates": candidates,
        }
        await self.session.send("human_prompt", prompt_data)
        self.pending_future = asyncio.get_running_loop().create_future()
        self.current_action = "assassinate"
        try:
            res = await self.pending_future
            target = res.get("target")
            if target is not None and int(target) in candidates:
                return int(target)
            return candidates[0]
        finally:
            self.pending_future = None
            self.current_action = None
            await self.session.send("human_prompt_clear", {"action": "assassinate"})
