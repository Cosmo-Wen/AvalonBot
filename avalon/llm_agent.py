"""
LLM-powered Agent for 5-Player Avalon.

Supports:
- Condition A (Baseline): Chat history & game log only
- Condition B (Proposed): Chat history + Structured Belief Graph injected into prompt
- Condition C: Deterministic rule-based belief updates + LLM decisions
Compatible with OpenAI, Boson AI, Groq, or any OpenAI-compatible API endpoint.
"""

import os
import json
import re
from typing import Dict, List, Optional, Any
import aiohttp

from .engine import Role, Phase, ROLE_NAMES, ROLE_SIDES
from .agents import Agent


SYSTEM_PROMPT_TEMPLATE = """You are Player {player_id} in a 5-player game of The Resistance: Avalon.
Your Secret Role: {role_name} ({side_name})

Role rules:
- Good Team (3 players): Merlin, 2 Loyal Servants. Goal: pass 3 quests and keep Merlin secret.
- Evil Team (2 players): Minion, Assassin. Goal: fail 3 quests OR assassinate Merlin at the end.
- Merlin sees who is Evil ({seen_evil_str}), but MUST NOT reveal this identity directly or the Assassin will shoot you!
- Evil players see each other ({seen_evil_str}).
- Servants do not know anyone's identity and must deduce who is evil through voting and proposals.

Personality:
- Be concise, strategic, and direct. Keep your spoken lines to 1-2 natural sentences.
- Never use markdown formatting, bullet points, or emojis in spoken discussion.
"""


class LLMAgent(Agent):
    """
    LLM-powered Avalon agent supporting Condition A and Condition B.
    """

    def __init__(
        self,
        player_id: int,
        role: Role,
        num_players: int = 5,
        condition: str = "belief_graph",  # "chat_only" or "belief_graph"
        model: str = "gpt-4o-mini",
        api_key: Optional[str] = None,
        base_url: str = "https://api.openai.com/v1",
        temperature: float = 0.7,
        seed: Optional[int] = None,
    ):
        super().__init__(player_id, role, num_players, condition, seed)
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("BOSON_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature

    def _build_system_prompt(self) -> str:
        seen_evil = self.private_info.get("seen_evil", [])
        seen_evil_str = f"Player(s) {seen_evil}" if seen_evil else "none"

        base_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            player_id=self.player_id,
            role_name=ROLE_NAMES[self.role],
            side_name="Good" if self.side else "Evil",
            seen_evil_str=seen_evil_str,
        )

        if self.condition in ("belief_graph", "rule_graph") and self.belief_graph:
            table = self.belief_graph.to_prompt_table()
            base_prompt += f"\n\n{table}\nUse your belief table to guide who you trust, accuse, and propose."

        return base_prompt

    async def _call_llm(self, user_prompt: str, json_mode: bool = False) -> str:
        """
        Executes an asynchronous chat completion request.
        """
        if not self.api_key:
            # Fallback mock for testing without live API keys
            return "I support this mission and want to ensure we pick trusted players."

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": "\n".join(self.chat_history[-15:]) + "\n\n" + user_prompt},
        ]

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": 150,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        url = f"{self.base_url}/chat/completions"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    err_msg = await resp.text()
                    raise RuntimeError(f"LLM API Error ({resp.status}): {err_msg}")
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()

    async def team_discussion(self, turn: int, round_num: int, leader: int, team_size: int) -> str:
        prompt = (
            f"Current state: Quest {turn + 1}, Proposal Round {round_num + 1}. Leader is Player {leader}.\n"
            f"Say 1-2 spoken sentences to the table. State who you trust or suspect, or advise on the team selection."
        )
        try:
            return await self._call_llm(prompt)
        except Exception as e:
            return f"As Player {self.player_id}, I want to make sure we keep evil players off Quest {turn + 1}."

    async def propose_team(self, turn: int, team_size: int) -> List[int]:
        prompt = (
            f"You are the Leader for Quest {turn + 1}. You must propose a team of exactly {team_size} distinct players.\n"
            f"Respond strictly in JSON format: {{\"team\": [list of {team_size} player indices]}}"
        )
        try:
            resp = await self._call_llm(prompt, json_mode=True)
            data = json.loads(resp)
            team = [int(x) for x in data["team"]]
            if len(set(team)) == team_size and all(0 <= p < self.num_players for p in team):
                return sorted(team)
        except Exception:
            pass

        # Fallback to heuristic
        team = [self.player_id]
        others = [p for p in range(self.num_players) if p != self.player_id]
        if self.belief_graph:
            others.sort(key=lambda p: self.belief_graph.p_evil[p])
        team.extend(others[: team_size - 1])
        return sorted(team)

    async def vote_on_team(self, turn: int, round_num: int, leader: int, team: List[int]) -> bool:
        if round_num >= 4:
            return True  # Hammer round auto-approves

        prompt = (
            f"Quest {turn + 1}, Round {round_num + 1}. Leader Player {leader} proposed team: {team}.\n"
            f"Do you approve this team? Respond strictly in JSON: {{\"approve\": true/false, \"reason\": \"short reason\"}}"
        )
        try:
            resp = await self._call_llm(prompt, json_mode=True)
            data = json.loads(resp)
            return bool(data.get("approve", True))
        except Exception:
            return self.player_id in team

    async def vote_on_quest(self, turn: int, team: List[int]) -> bool:
        if self.side:
            return True  # Good must pass

        prompt = (
            f"You are an Evil player on Quest {turn + 1} with team {team}.\n"
            f"Do you choose to Pass (to build trust) or Fail (to score a mission point for Evil)?\n"
            f"Respond strictly in JSON: {{\"pass_mission\": true/false}}"
        )
        try:
            resp = await self._call_llm(prompt, json_mode=True)
            data = json.loads(resp)
            return bool(data.get("pass_mission", False))
        except Exception:
            return False

    async def assassinate(self) -> int:
        good_players = [p for p in range(self.num_players) if p not in self.private_info.get("seen_evil", []) and p != self.player_id]
        prompt = (
            f"Good succeeded 3 quests! You are the Assassin. You must assassinate Merlin among {good_players}.\n"
            f"Respond strictly in JSON: {{\"target\": player_id}}"
        )
        try:
            resp = await self._call_llm(prompt, json_mode=True)
            data = json.loads(resp)
            target = int(data.get("target"))
            if target in good_players:
                return target
        except Exception:
            pass
        return self.rng.choice(good_players) if good_players else 0
