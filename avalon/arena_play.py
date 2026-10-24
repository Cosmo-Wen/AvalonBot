"""
Plays one AvalonBot game for the arena runner (`arena/`, configured with
`play_fn: avalon.arena_play:play_game`).

The arena supplies the seeded deal (roles and first leader), the per-game JSONL log, retries and
resume; this module runs the game with AvalonBot's engine and agents. Every game event is written to
the log in the arena's event format and, as it happens, fed through `ArenaGraphAdapter`, so the log
also yields each player's belief graph (`belief_graphs` at game end), whatever the condition.

Seats: `provider: openai` plays an LLMAgent against an OpenAI-compatible endpoint (OPENAI_API_KEY,
OPENAI_BASE_URL, and the seat's `model`); `provider: codex_cli` uses the Codex login; `provider: fake` plays the offline HeuristicAgent. The good
team plays `cfg.condition`; the evil team always plays chat-only (A).
"""

import asyncio
import os
import random
import time
import weakref
from typing import Any, Dict, List, Optional

import aiohttp

from arena.backends import TransientBackendError, BackendError, FatalBackendError, NotLoggedIn, UsageLimitReached, redact_keys
from arena.config import ArenaConfig
from arena.events import EventLog
from arena.seeding import GameSetup

from .agents import Agent, HeuristicAgent
from .arena_adapter import ARENA_ROLES, ArenaGraphAdapter
from .belief_graph import brier_score, spy_id_accurate
from .engine import ROLE_SIDES, Role
from .llm_agent import LLMAgent
from .runner import AvalonGameRunner

ROLE_TO_ARENA = {role: name for name, role in ARENA_ROLES.items()}


# one cap per event loop on concurrent API requests, shared by every game and seat
_inflight = weakref.WeakKeyDictionary()


def _inflight_semaphore(limit: int) -> asyncio.Semaphore:
    per_loop = _inflight.setdefault(asyncio.get_running_loop(), {})
    if limit not in per_loop:
        per_loop[limit] = asyncio.Semaphore(limit)
    return per_loop[limit]


def is_gateway_rejection(message: str) -> bool:
    r"""A 429 the gateway sent before running the request (concurrency or rate limit, not quota), or
    a 502/503 "temporarily unavailable". Neither request was served, so retrying can't be billed twice."""
    lowered = message.lower()
    if ("(502)" in message or "(503)" in message) and "temporarily unavailable" in lowered:
        return True
    return "(429)" in message and ("rate_limit_error" in lowered or "concurrency" in lowered) \
        and not any(w in lowered for w in ("quota", "allowance"))


class LoggedLLMAgent(LLMAgent):
    r"""LLMAgent whose every API call is logged as an `llm_call` (or `llm_error`) event.

    Requests share a process-wide cap (`max_inflight_requests`), and gateway rejections (429
    concurrency/rate limits) are retried with backoff, since LLMAgent would otherwise catch them and
    play a fallback move. Failed connections (DNS, refused) are retried too: the request never left.
    Each request is also bounded by `request_timeout_s` (`llm_timeout_s`): a stalled connection
    otherwise holds its in-flight slot indefinitely. A timed-out request is retried as well; it may
    already have been served, so this can bill one call twice. LLMAgent also falls back on an
    expired key or exhausted allowance; the first such error is kept in `fatal`, later calls fail immediately (no further spend), and the
    game is reported as interrupted afterwards.
    """

    def __init__(self, *args, log: EventLog, max_inflight: int = 6, max_retries: int = 5,
                 backoff_base_s: float = 2.0, backoff_max_s: float = 60.0,
                 request_timeout_s: float = 180.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.log = log
        self.max_inflight = max_inflight
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.backoff_max_s = backoff_max_s
        self.request_timeout_s = request_timeout_s
        self.fatal: Optional[BackendError] = None
        self.calls = 0
        self.errors = 0
        self.retries = 0

    async def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.fatal is not None:
            raise RuntimeError(f"skipped after earlier error: {self.fatal}")
        prompt = payload["messages"][-1]["content"]
        tool_choice = payload.get("tool_choice")
        attempt = 0
        while True:
            start = time.monotonic()
            try:
                async with _inflight_semaphore(self.max_inflight):
                    start = time.monotonic()
                    data = await asyncio.wait_for(super()._post(payload), self.request_timeout_s)
                break
            except Exception as exc:
                timed_out = isinstance(exc, asyncio.TimeoutError)
                message = f"request timed out after {self.request_timeout_s}s" if timed_out else redact_keys(str(exc))
                retryable = isinstance(exc, TransientBackendError) or timed_out or isinstance(exc, aiohttp.ClientConnectorError) or is_gateway_rejection(message)
                if retryable and attempt < self.max_retries:
                    delay = random.uniform(0, min(self.backoff_max_s, self.backoff_base_s * 2 ** attempt))
                    self.retries += 1
                    self.log.emit("retry", scope="llm_call", seat=self.player_id, attempt=attempt,
                                  error=message[:200], delay_s=round(delay, 2))
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue
                self.errors += 1
                self.log.emit("llm_error", seat=self.player_id, model=self.model, error=message,
                              latency_s=round(time.monotonic() - start, 3))
                self.fatal = self.fatal or (exc if isinstance(exc, BackendError) else classify_http_error(message))
                raise
        self.calls += 1
        msg = data["choices"][0]["message"]
        calls = [{"name": c["function"]["name"], "arguments": c["function"].get("arguments")}
                 for c in msg.get("tool_calls") or []]
        usage = data.get("usage") or {}
        self.log.emit(
            "llm_call", seat=self.player_id, source="seat", model=data.get("model") or self.model,
            prompt=prompt, response=msg.get("content") or "", tool_calls=calls,
            tool_choice=tool_choice if isinstance(tool_choice, str) else (tool_choice or {}).get("function", {}).get("name"),
            input_tokens=usage.get("prompt_tokens", 0), output_tokens=usage.get("completion_tokens", 0),
            cost_usd=0.0, latency_s=round(time.monotonic() - start, 3),
        )
        return data


def classify_http_error(message: str) -> Optional[BackendError]:
    r"""Errors that should stop the whole run instead of letting the game play on fallbacks."""
    lowered = message.lower()
    if "(401)" in message or "(403)" in message:
        if any(w in lowered for w in ("expired", "quota", "allowance")):
            return UsageLimitReached(f"API key expired or out of allowance: {message[:200]}")
        return NotLoggedIn(f"API key rejected: {message[:200]}")
    if "(402)" in message or ("(429)" in message and any(w in lowered for w in ("quota", "allowance"))):
        return UsageLimitReached(f"API allowance exhausted: {message[:200]}")
    if "(404)" in message:
        return FatalBackendError(f"model or endpoint unavailable: {message[:200]}")
    return None


def build_agents(setup: GameSetup, cfg: ArenaConfig, log: EventLog) -> Dict[int, Agent]:
    agents: Dict[int, Agent] = {}
    for seat, spec in enumerate(setup.seat_specs):
        role = ARENA_ROLES[setup.role_names[seat]]
        condition = cfg.condition if role == Role.LOYAL_SERVANT else "chat_only"
        if not any(name == "Percival" for name in setup.role_names):
            condition = cfg.condition if ROLE_SIDES[role] else "chat_only"
        seed = setup.agent_seeds[seat]
        if spec.provider == "fake":
            agents[seat] = HeuristicAgent(player_id=seat, role=role, condition=condition, seed=seed, percival_condition=cfg.percival_condition)
        elif spec.provider in ("openai", "codex_cli"):
            transport = None
            if spec.provider == "codex_cli":
                from arena.codex_backend import CodexCLIBackend
                transport = CodexCLIBackend(spec.model, cfg, spec.effort)
            if spec.provider == "openai" and not os.getenv("OPENAI_API_KEY"):
                raise NotLoggedIn("no OpenAI API key: set OPENAI_API_KEY (for example in a local .env file)")
            agents[seat] = LoggedLLMAgent(player_id=seat, role=role, condition=condition, model=spec.model,
                                          seed=seed, log=log, transport=transport, percival_condition=cfg.percival_condition, max_inflight=cfg.max_inflight_requests,
                                          max_retries=cfg.llm_max_retries, backoff_base_s=cfg.backoff_base_s,
                                          backoff_max_s=cfg.backoff_max_s, request_timeout_s=cfg.llm_timeout_s)
        else:
            raise FatalBackendError(
                f"provider {spec.provider!r} isn't supported for AvalonBot games: LLMAgent needs an "
                f"OpenAI-compatible endpoint with tool calls (use provider openai or codex_cli, or fake for offline)"
            )
    return agents


class EventBridge:
    r"""Writes AvalonBot runner events to the arena log, in the arena's format, and feeds the adapter."""

    def __init__(self, log: EventLog, adapter: ArenaGraphAdapter):
        self.log = log
        self.adapter = adapter
        self.agents = {}

    def emit(self, event_type: str, **data: Any) -> None:
        self.adapter.feed(self.log.emit(event_type, **data))

    def __call__(self, event_type: str, d: Dict[str, Any], recipients: List[int]) -> None:
        if event_type == "utterance":
            self.emit("discussion", quest=d["turn"], round=d["round_num"], seat=d["speaker"], text=d["text"])
        elif event_type == "evil_chat":
            self.emit("evil_chat", quest=d["turn"], seat=d["speaker"], text=d["text"], recipients=recipients)
        elif event_type == "team_proposed":
            self.emit("team_proposed", quest=d["turn"], round=d["round_num"], leader=d["leader"], team=sorted(d["team"]))
        elif event_type == "team_vote_result":
            votes = {int(p): bool(v) for p, v in d["votes"].items()}
            self.emit("team_votes", quest=d["turn"], round=d["round_num"], votes=[int(votes[p]) for p in sorted(votes)])
            self.emit("team_result", quest=d["turn"], round=d["round_num"], team=sorted(d["team"]), approved=bool(d["approved"]))
        elif event_type == "quest_cards":
            self.emit("quest_votes", quest=d["turn"], team=sorted(d["team"]),
                      votes={int(p): int(card) for p, card in d["cards"].items()})
        elif event_type == "quest_result":
            self.emit("quest_result", quest=d["turn"], team=sorted(d["team"]), succeeded=bool(d["success"]),
                      num_fails=int(d["num_fails"]))
        elif event_type == "assassination":
            self.emit("assassination", **d)
        if event_type in ("team_proposed", "team_vote_result", "quest_result"):
            for seat, agent in self.agents.items():
                if agent.memory is not None and agent.memory.percival is not None:
                    self.emit("percival_beliefs", seat=seat, after_event=event_type,
                              **agent.memory.percival.snapshot())


async def play_game(setup: GameSetup, cfg: ArenaConfig, log: EventLog) -> Dict[str, Any]:
    r"""Plays one AvalonBot game and returns the arena `game_end` payload."""
    adapter = ArenaGraphAdapter(merlin_graph=False)
    bridge = EventBridge(log, adapter)
    agents = build_agents(setup, cfg, log)
    bridge.agents = agents
    roles = {seat: ARENA_ROLES[name] for seat, name in enumerate(setup.role_names)}

    bridge.emit(
        "game_start",
        seed=setup.seed,
        config_hash=cfg.config_hash(),
        condition=cfg.condition,
        percival_condition=cfg.percival_condition,
        quest_leader=setup.quest_leader,
        seats=[
            {"seat": i, "participant": setup.seat_participants[i], "name": spec.name, "agent": spec.agent,
             "provider": spec.provider, "model": spec.model, "role": setup.role_names[i],
             "condition": agents[i].condition, "agent_seed": setup.agent_seeds[i]}
            for i, spec in enumerate(setup.seat_specs)
        ],
    )

    runner = AvalonGameRunner(agents=agents, tts_client=None, verbose=False, on_event=bridge)
    metrics = await runner.run_game(preset_roles=roles, preset_leader=setup.quest_leader)

    fatal = next((a.fatal for a in agents.values() if getattr(a, "fatal", None) is not None), None)
    if fatal is not None:
        raise fatal  # the game ran on fallbacks after the endpoint refused us; don't count it

    evil = {p for p, role in roles.items() if not ROLE_SIDES[role]}
    true_sides = [int(ROLE_SIDES[roles[p]]) for p in range(len(roles))]
    believed = []
    for p in range(len(roles)):
        p_evil = metrics.final_p_evil.get(p)
        believed.append(None if p_evil is None else [1.0 if q == p else 1.0 - p_evil[q] for q in range(len(roles))])
    bridge.emit("beliefs", true_sides=true_sides, believed=believed, belief_paths=metrics.belief_paths,
                belief_fallbacks=metrics.belief_fallbacks)

    # the same graph, rebuilt from the logged events alone (rule beliefs, no talk edges)
    bridge.emit("belief_graphs", graphs={
        seat: {"edges": len(m.graph.edges), "p_evil": dict(m.beliefs.p_evil) if m.beliefs else (m.percival.p_evil if m.percival else None),
               "percival": m.percival.snapshot() if m.percival else None}
        for seat, m in adapter.memories.items()
    })

    good_won = metrics.good_victory
    if good_won:
        reason = "missions_and_assassin_missed"
    elif metrics.assassination_target is not None and metrics.assassination_target == metrics.merlin_id:
        reason = "assassination"
    else:
        reason = "missions"
    seats = []
    for i, spec in enumerate(setup.seat_specs):
        good = ROLE_SIDES[roles[i]]
        p_evil = metrics.final_p_evil.get(i)
        seats.append({
            "seat": i, "name": spec.name, "agent": spec.agent, "model": spec.model,
            "role": setup.role_names[i], "condition": agents[i].condition,
            "side": "good" if good else "evil", "won": good == good_won,
            # top-2 suspects exactly the evil pair (Servants only; None for players without P(evil))
            "deduction_acc": None if p_evil is None else float(spy_id_accurate(p_evil, evil)),
            "brier": None if p_evil is None else brier_score(p_evil, evil),
            "llm_calls": getattr(agents[i], "calls", 0), "llm_errors": getattr(agents[i], "errors", 0),
            "llm_retries": getattr(agents[i], "retries", 0),
        })
    return {
        "status": "completed",
        "winner": "good" if good_won else "evil",
        "reason": reason,
        "condition": cfg.condition,
        "percival_condition": cfg.percival_condition,
        "percival_metrics": metrics.percival_metrics,
        "quest_results": list(runner.engine.quest_results),
        "proposals": len(runner.engine.vote_history),
        "merlin_survived": metrics.merlin_survived,
        "belief_paths": metrics.belief_paths,
        "seats": seats,
    }
