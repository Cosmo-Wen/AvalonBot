"""
LLM-powered Agent for 5-Player Avalon.

Every agent reads only its own memory (see MEMORY_MODEL.md). For Loyal Servants:
- Condition A (chat_only): full observation log plus free-text notes from a reflection call
- Condition B (belief_graph): graph table plus recall tools; P(evil) from its own extraction call
- Condition C (rule_graph): graph table plus recall tools; P(evil) from the Condition C rule
Merlin and the evil players see their full observation log in every condition.
Compatible with OpenAI, Boson AI, Groq, or any OpenAI-compatible API endpoint.
"""

import os
import json
from itertools import combinations
from typing import Dict, List, Optional, Any, Sequence
import aiohttp

from .engine import Role, Phase, ROLE_NAMES, ROLE_SIDES
from .agents import Agent
from .belief_graph import PairBelief
from .tools import RECALL_TOOL_DEFINITIONS, get_tool


SYSTEM_PROMPT_TEMPLATE = """You are Player {player_id} in a 5-player game of The Resistance: Avalon.
Your Secret Role: {role_name} ({side_name})

Role rules:
- Good Team (3 players): Merlin, 2 Loyal Servants. Goal: pass 3 quests and keep Merlin secret.
- Evil Team (2 players): Minion, Assassin. Goal: fail 3 quests OR assassinate Merlin at the end.
- Merlin sees who is Evil ({seen_evil_str}), but MUST NOT reveal this identity directly or the Assassin will shoot you!
- Evil players see each other ({seen_evil_str}).
- Servants do not know anyone's identity and must deduce who is evil through voting and proposals.
- A failed quest proves at least one team member is evil. A passed quest proves nothing, since evil may pass.

Your memory below holds only what you observed and what you yourself thought. Entries are numbered (#).

Personality:
- Be concise, strategic, and direct. Keep your spoken lines to 1-2 natural sentences.
- Never use markdown formatting, bullet points, or emojis in spoken discussion.
"""

# Opt-in Merlin strategy (`merlin_strategy: hidden`): the Assassin reads Merlin from accusations that
# land too accurately, so steer quietly and only say what a servant could also have worked out.
MERLIN_HIDDEN_RULES = """
How you play Merlin (the Assassin is watching who reads evil correctly):
- Only argue from public evidence anyone could cite: failed quests, team members, votes. Never from what you saw.
- Never be the first or the most confident to accuse someone. Echo a servant's suspicion instead of leading.
- Steer mostly with your votes. When you speak, sound as uncertain as a servant would.
- Now and then voice mild doubt about a good player, and don't defend a good player too eagerly.
- If a servant is already pushing the right read, let them carry it.
"""

# `merlin_strategy: cover` adds this: Merlin's votes and proposals are made by code (see
# LLMAgent._cover_vote), so the speech only has to stay consistent with public evidence.
MERLIN_COVER_RULES = """- Your votes and team picks follow the public evidence, the way a Servant's would. When you explain
  one, cite only that evidence: failed quests, who was on them, how people voted.
"""

# A team "looks clean" to a Servant when its P(no evil) under the public counting rule is at least
# this share of the best any same-size team including them could get.
COVER_APPROVE_RATIO = 0.75

EXTRACTION_PROMPT = """Discussion round {label} just ended. Record what you heard into your private memory by calling record_observations.

This round's lines:
{transcript}

Rules:
- edges: only for what players actually said. Cite the # numbers of the speaker's own lines in sources. Quote at most 10 words.
- accused/defended point at a player id. backed_team/opposed_team point at an existing team label like Q1.1. claimed_role names a role.
- notes: your own read on each player, at most 15 words each.
{p_evil_rule}"""

P_EVIL_RULE_B = (
    "- p_evil: your probability that each of players {opponents} is evil. Exactly 2 of them are evil, so the values "
    "sum to 2. Each failed team's members must sum to at least its number of fails. Votes and quest results "
    "outweigh talk."
)
P_EVIL_RULE_C = "- Leave out p_evil. Your beliefs are computed by code from votes, quest results, and these edges."

MOCK_LINE = "I support this mission and want to ensure we pick trusted players."
MAX_RECALL_STEPS = 2


class LLMAgent(Agent):
    """
    LLM-powered Avalon agent for conditions A, B, and C.
    """

    llm_beliefs = True

    def __init__(
        self,
        player_id: int,
        role: Role,
        num_players: int = 5,
        condition: str = "belief_graph",  # "chat_only", "belief_graph", or "rule_graph"
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.7,
        seed: Optional[int] = None,
        merlin_graph: bool = False,
        merlin_strategy: str = "default",  # "hidden": MERLIN_HIDDEN_RULES; "cover": also votes/picks by public evidence
    ):
        super().__init__(player_id, role, num_players, condition, seed, merlin_graph=merlin_graph)
        # Unset arguments come from the standard OpenAI variables, so a local .env can route every
        # agent to an OpenAI-compatible endpoint (e.g. Boson Marketplace) without code changes.
        self.model = model or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("BOSON_API_KEY", "")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.temperature = temperature
        self.merlin_strategy = merlin_strategy

    @property
    def _offers_recall(self) -> bool:
        return self.is_servant and self.uses_graph and self.memory is not None

    def _build_system_prompt(self) -> str:
        seen_evil = self.private_info.get("seen_evil", [])
        seen_evil_str = f"Player(s) {seen_evil}" if seen_evil else "none"

        prompt = SYSTEM_PROMPT_TEMPLATE.format(
            player_id=self.player_id,
            role_name=ROLE_NAMES[self.role],
            side_name="Good" if self.side else "Evil",
            seen_evil_str=seen_evil_str,
        )
        if self.role == Role.MERLIN and self.merlin_strategy in ("hidden", "cover"):
            prompt += MERLIN_HIDDEN_RULES
        if self._covers:
            prompt += MERLIN_COVER_RULES
        return prompt

    def _memory_context(self) -> str:
        m = self.memory
        if m is None:
            return ""
        parts = [m.render_private()]
        if self._offers_recall:
            parts.append("Your belief graph:\n" + m.render_table())
            quest = m.log[-1].quest if m.log else 1
            recent = m.render_log(m.entries_since_quest(quest - 1))
            parts.append("Recent events (use the recall tools for older ones):\n" + (recent or "none yet"))
        else:
            if m.merlin is not None:
                parts.append(
                    "Your Merlin graph (P(Merlin): how likely each good player is Merlin, "
                    "based on how accurate their votes and accusations have been):\n" + m.render_table()
                )
            parts.append("Everything you have observed:\n" + (m.render_log() or "nothing yet"))
            if m.free_notes:
                parts.append("Your private notes:\n" + m.render_notes())
            parts.append(m.graph.render_my_record())
        return "\n\n".join(parts)

    def _messages(self, user_prompt: str) -> List[Dict[str, Any]]:
        return [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": self._memory_context() + "\n\n" + user_prompt},
        ]

    async def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    err_msg = await resp.text()
                    raise RuntimeError(f"LLM API Error ({resp.status}): {err_msg}")
                return await resp.json()

    @staticmethod
    def _parse_args(call: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return json.loads(call["function"].get("arguments") or "{}")
        except (KeyError, TypeError, ValueError):
            return {}

    async def _call_llm(self, user_prompt: str, json_mode: bool = False, max_tokens: int = 150) -> str:
        """
        Executes an asynchronous chat completion request.
        """
        if not self.api_key:
            # Fallback mock for testing without live API keys
            return MOCK_LINE

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": self._messages(user_prompt),
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        data = await self._post(payload)
        return data["choices"][0]["message"]["content"].strip()

    async def _call_llm_tool(self, user_prompt: str, tool_name: str) -> Dict[str, Any]:
        """
        Calls the LLM until it uses tool_name. Servants in B and C may first use the
        recall tools over their own memory, for up to MAX_RECALL_STEPS rounds.
        """
        if not self.api_key:
            return {}

        messages = self._messages(user_prompt)
        tools = [get_tool(tool_name)]

        if self._offers_recall:
            tools = tools + RECALL_TOOL_DEFINITIONS
            try:
                for _ in range(MAX_RECALL_STEPS):
                    data = await self._post({
                        "model": self.model,
                        "messages": messages,
                        "tools": tools,
                        "tool_choice": "required",
                        "temperature": self.temperature,
                    })
                    msg = data["choices"][0]["message"]
                    calls = msg.get("tool_calls") or []
                    if not calls:
                        break
                    for call in calls:
                        if call["function"]["name"] == tool_name:
                            return self._parse_args(call)
                    messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": calls})
                    for call in calls:
                        result = self.memory.run_tool(call["function"]["name"], self._parse_args(call))
                        messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
            except RuntimeError:
                pass  # Provider may not support tool_choice "required"; force the tool below.

        data = await self._post({
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": {"type": "function", "function": {"name": tool_name}},
            "temperature": self.temperature,
        })
        choice = data["choices"][0]["message"]
        for call in choice.get("tool_calls") or []:
            if call["function"]["name"] == tool_name:
                return self._parse_args(call)
        return {}

    async def after_discussion(self, turn: int, round_num: int) -> None:
        """
        This player's own read of the discussion round. Servants: reflection in A, extraction
        in B and C. Evil players with a Merlin graph: extraction for talk edges only.
        """
        if self.memory is None or not (self.is_servant or self.reads_talk):
            return
        m = self.memory
        label = f"Q{turn + 1}.{round_num + 1}"
        transcript = m.render_log(m.discussion_entries(turn + 1, round_num + 1)) or "Nobody spoke."

        if not self.reads_talk:
            if not self.api_key:
                return
            prompt = (
                f"Private reflection after discussion round {label}. Nobody else will see this. "
                f"In at most 40 words, note who you suspect and why, citing # numbers.\n\nThis round:\n{transcript}"
            )
            try:
                m.add_free_note(await self._call_llm(prompt, max_tokens=80))
            except Exception:
                pass
            return

        opponents = [p for p in range(self.num_players) if p != self.player_id]
        llm_sets_p_evil = m.beliefs is not None and m.belief_mode == "llm"
        p_evil_rule = P_EVIL_RULE_B.format(opponents=opponents) if llm_sets_p_evil else P_EVIL_RULE_C
        prompt = EXTRACTION_PROMPT.format(label=label, transcript=transcript, p_evil_rule=p_evil_rule)
        try:
            args = await self._call_llm_tool(prompt, "record_observations")
        except Exception:
            args = {}
        m.add_talk_edges(args.get("edges") or [])
        m.set_notes(args.get("notes") or {})

        if not llm_sets_p_evil:
            return
        # Beyond the coherence rules, reject P(evil) that ignores the failed quests (all 0.5, or a
        # failed team not ranked as the top suspects). Re-ask once, then use the pair-counting rule.
        errors = m.apply_llm_beliefs(args.get("p_evil"), check_evidence=True)
        if not errors:
            m.record_belief_path("llm")
            return
        retry = (
            prompt + "\n\nYour p_evil was rejected: " + "; ".join(errors)
            + ". Call record_observations again with corrected p_evil."
        )
        try:
            retry_args = await self._call_llm_tool(retry, "record_observations")
        except Exception:
            retry_args = {}
        if m.apply_llm_beliefs(retry_args.get("p_evil"), check_evidence=True):
            m.fall_back_to_rule()
            m.record_belief_path("rule_fallback")
        else:
            m.record_belief_path("llm_retry")

    async def final_beliefs(self) -> Optional[Dict[int, float]]:
        m = self.memory
        if m is None or m.beliefs is None:
            return None
        if self.uses_graph:
            return dict(m.beliefs.p_evil)

        # Condition A keeps no beliefs during play; it is asked once, at game end.
        if self.api_key:
            opponents = [p for p in range(self.num_players) if p != self.player_id]
            prompt = (
                f"The game is over. Call report_beliefs with your probability that each of players {opponents} "
                f"is evil. Exactly 2 of them are evil, so the values sum to 2."
            )
            try:
                args = await self._call_llm_tool(prompt, "report_beliefs")
            except Exception:
                args = {}
            if not m.apply_llm_beliefs(args.get("p_evil")):
                return dict(m.beliefs.p_evil)
        m.fall_back_to_rule()
        return dict(m.beliefs.p_evil)

    async def evil_discussion(self, turn: int) -> str:
        prompt = (
            "Good has passed 3 quests. Only your evil partner hears this. "
            "In 1-2 sentences, say who you think Merlin is and why."
        )
        try:
            return await self._call_llm(prompt)
        except Exception:
            return ""

    async def team_discussion(self, turn: int, round_num: int, leader: int, team_size: int) -> str:
        prompt = (
            f"Current state: Quest {turn + 1}, Proposal Round {round_num + 1}. Leader is Player {leader}.\n"
            f"Say 1-2 spoken sentences to the table. State who you trust or suspect, or advise on the team selection."
        )
        try:
            return await self._call_llm(prompt)
        except Exception as e:
            return f"As Player {self.player_id}, I want to make sure we keep evil players off Quest {turn + 1}."

    def _valid_team(self, team: List[int], team_size: int) -> bool:
        return len(set(team)) == team_size and all(0 <= p < self.num_players for p in team)

    # Merlin's cover (merlin_strategy: cover)

    @property
    def _covers(self) -> bool:
        return self.role == Role.MERLIN and self.merlin_strategy == "cover"

    def set_private_info(self, info: Dict[str, Any]):
        super().set_private_info(info)
        if self._covers:
            self.memory.cover = PairBelief(self.player_id, self.num_players)

    def _p_clean(self, team: Sequence[int]) -> float:
        r"""P(no evil on the team) under the public counting rule, from Merlin's seat."""
        others = set(team) - {self.player_id}
        return sum(w for pair, w in self.memory.cover.rule_weights().items() if not others & set(pair))

    def _best_p_clean(self, size: int) -> float:
        others = [p for p in range(self.num_players) if p != self.player_id]
        return max(self._p_clean((self.player_id,) + rest) for rest in combinations(others, size - 1))

    def _match_point(self, team: Sequence[int]) -> bool:
        r"""Evil is on the team and already has a fail: passing it would give evil a 2nd or 3rd fail."""
        fails = len(self.memory.graph.failed_teams())
        return fails >= 1 and bool(set(team) & set(self.private_info.get("seen_evil", [])))

    def _cover_vote(self, turn: int, round_num: int, team: List[int]) -> bool:
        p = self._p_clean(team)
        approve = p >= COVER_APPROVE_RATIO * self._best_p_clean(len(team))
        why = f"public evidence: P(no evil on team) = {p:.2f}"
        if approve and self._match_point(team):
            approve, why = False, "override: evil on the team at match point"
        self._record_reason(turn, round_num, "approved" if approve else "rejected", f"cover vote ({why})")
        return approve

    def _cover_team(self, turn: int, round_num: int, size: int) -> List[int]:
        others = [p for p in range(self.num_players) if p != self.player_id]
        teams = [sorted((self.player_id,) + rest) for rest in combinations(others, size - 1)]
        best = max(self._p_clean(t) for t in teams)
        plausible = [t for t in teams if self._p_clean(t) >= COVER_APPROVE_RATIO * best]
        top = [t for t in plausible if self._p_clean(t) == best]
        pick = self.rng.choice(top)
        if self._match_point(pick):
            # don't lead evil onto a deciding quest: any publicly plausible team without them
            clean = [t for t in plausible if not self._match_point(t)]
            if clean:
                pick = self.rng.choice(clean)
        self._record_reason(turn, round_num, "proposed", f"cover pick (public P(no evil) = {self._p_clean(pick):.2f})")
        return pick

    async def propose_team(self, turn: int, team_size: int) -> List[int]:
        round_num = self._current_round_num()
        if self._covers:
            return self._cover_team(turn, round_num, team_size)
        prompt = f"You are the Leader for Quest {turn + 1}. Call propose_team with exactly {team_size} distinct players."
        try:
            # 1. Try Tool Calling first
            args = await self._call_llm_tool(prompt, "propose_team")
            if "team" in args:
                team = [int(x) for x in args["team"]]
                if self._valid_team(team, team_size):
                    self._record_reason(turn, round_num, "proposed", str(args.get("reasoning", "")))
                    return sorted(team)

            # 2. Try JSON mode fallback
            resp = await self._call_llm(
                prompt + " Output strictly JSON: {\"team\": [...], \"reasoning\": \"...\"}.", json_mode=True
            )
            data = json.loads(resp)
            team = [int(x) for x in data["team"]]
            if self._valid_team(team, team_size):
                self._record_reason(turn, round_num, "proposed", str(data.get("reasoning", "")))
                return sorted(team)
        except Exception:
            pass

        # 3. Fallback: least suspected players, when this player has an estimate
        team = [self.player_id]
        others = [p for p in range(self.num_players) if p != self.player_id]
        if all(self.suspicion(p) is not None for p in others):
            others.sort(key=lambda p: self.suspicion(p))
        team.extend(others[: team_size - 1])
        self._record_reason(turn, round_num, "proposed", "fallback: picked the players I suspect least")
        return sorted(team)

    async def vote_on_team(self, turn: int, round_num: int, leader: int, team: List[int]) -> bool:
        if round_num >= 4:
            self._record_reason(turn, round_num, "approved", "hammer round auto-approves")
            return True  # Hammer round auto-approves
        if self._covers:
            return self._cover_vote(turn, round_num, team)

        prompt = f"Quest {turn + 1}, Round {round_num + 1}. Leader Player {leader} proposed team {team}. Call vote_on_team to approve or reject."
        try:
            # 1. Try Tool Calling first
            args = await self._call_llm_tool(prompt, "vote_on_team")
            if "approve" in args:
                approve = bool(args["approve"])
                self._record_reason(turn, round_num, "approved" if approve else "rejected", str(args.get("reason", "")))
                return approve

            # 2. Try JSON mode fallback
            resp = await self._call_llm(prompt + " Output JSON: {\"approve\": true/false, \"reason\": \"...\"}", json_mode=True)
            data = json.loads(resp)
            approve = bool(data.get("approve", True))
            self._record_reason(turn, round_num, "approved" if approve else "rejected", str(data.get("reason", "")))
            return approve
        except Exception:
            approve = self.player_id in team
            self._record_reason(turn, round_num, "approved" if approve else "rejected", "fallback: approve only teams I am on")
            return approve

    async def vote_on_quest(self, turn: int, team: List[int]) -> bool:
        if self.side:
            return True  # Good must pass

        prompt = f"You are Evil on Quest {turn + 1} with team {team}. Call vote_on_quest to Pass (bluff) or Fail (score)."
        try:
            # 1. Try Tool Calling first
            args = await self._call_llm_tool(prompt, "vote_on_quest")
            if "pass_quest" in args:
                return bool(args["pass_quest"])

            # 2. Try JSON mode fallback
            resp = await self._call_llm(prompt + " Output JSON: {\"pass_quest\": true/false}", json_mode=True)
            data = json.loads(resp)
            return bool(data.get("pass_quest", False))
        except Exception:
            return False

    async def assassinate(self) -> int:
        good_players = [p for p in range(self.num_players) if p not in self.private_info.get("seen_evil", []) and p != self.player_id]
        prompt = f"Good succeeded 3 quests! You are the Assassin. Call assassinate with your target player ID among {good_players}."
        if self.memory is not None and self.memory.merlin is not None:
            prompt += " Weigh your Merlin graph and what your partner said."
        try:
            # 1. Try Tool Calling first
            args = await self._call_llm_tool(prompt, "assassinate")
            if "target" in args and int(args["target"]) in good_players:
                return int(args["target"])

            # 2. Try JSON mode fallback
            resp = await self._call_llm(prompt + " Output JSON: {\"target\": player_id}", json_mode=True)
            data = json.loads(resp)
            target = int(data.get("target"))
            if target in good_players:
                return target
        except Exception:
            pass
        guess = self.merlin_guess()
        if guess is not None:
            return guess
        return self.rng.choice(good_players) if good_players else 0
