"""
Plays one AvalonBot game for the arena runner (`arena/`, configured with
`play_fn: avalon.arena_play:play_game`).

The arena supplies the seeded deal (roles and first leader), the per-game JSONL log, retries and
resume; this module runs the game with AvalonBot's engine and agents. Every game event is written to
the log in the arena's event format and, as it happens, fed through `ArenaGraphAdapter`, so the log
also yields each player's belief graph (`belief_graphs` at game end), whatever the condition.

Seats: `provider: openai` plays an LLMAgent against an OpenAI-compatible endpoint (OPENAI_API_KEY,
OPENAI_BASE_URL, and the seat's `model`); `provider: fake` plays the offline HeuristicAgent. The good
team plays `cfg.condition`; the evil team always plays chat-only (A).
"""

import os
import time
from typing import Any, Dict, List, Optional

from arena.backends import BackendError, FatalBackendError, NotLoggedIn, UsageLimitReached, redact_keys
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


class LoggedLLMAgent(LLMAgent):
    r"""LLMAgent whose every API call is logged as an `llm_call` (or `llm_error`) event.

    LLMAgent catches API errors and falls back, so an expired key or exhausted allowance would
    otherwise let the game finish on fallbacks. The first such error is kept in `fatal`; later calls
    fail immediately (no further spend) and the game is reported as interrupted afterwards.
    """

    def __init__(self, *args, log: EventLog, **kwargs):
        super().__init__(*args, **kwargs)
        self.log = log
        self.fatal: Optional[BackendError] = None
        self.calls = 0
        self.errors = 0

    async def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.fatal is not None:
            raise RuntimeError(f"skipped after earlier error: {self.fatal}")
        prompt = payload["messages"][-1]["content"]
        tool_choice = payload.get("tool_choice")
        start = time.monotonic()
        try:
            data = await super()._post(payload)
        except Exception as exc:
            self.errors += 1
            message = redact_keys(str(exc))
            self.log.emit("llm_error", seat=self.player_id, model=self.model, error=message,
                          latency_s=round(time.monotonic() - start, 3))
            self.fatal = self.fatal or classify_http_error(message)
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
        condition = cfg.condition if ROLE_SIDES[role] else "chat_only"
        seed = setup.agent_seeds[seat]
        if spec.provider == "fake":
            agents[seat] = HeuristicAgent(player_id=seat, role=role, condition=condition, seed=seed)
        elif spec.provider == "openai":
            if not os.getenv("OPENAI_API_KEY"):
                raise NotLoggedIn("no OpenAI API key: set OPENAI_API_KEY (for example in a local .env file)")
            agents[seat] = LoggedLLMAgent(player_id=seat, role=role, condition=condition, model=spec.model,
                                          seed=seed, log=log)
        else:
            raise FatalBackendError(
                f"provider {spec.provider!r} isn't supported for AvalonBot games: LLMAgent needs an "
                f"OpenAI-compatible endpoint with tool calls (use provider openai, or fake for offline)"
            )
    return agents


class EventBridge:
    r"""Writes AvalonBot runner events to the arena log, in the arena's format, and feeds the adapter."""

    def __init__(self, log: EventLog, adapter: ArenaGraphAdapter):
        self.log = log
        self.adapter = adapter

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


async def play_game(setup: GameSetup, cfg: ArenaConfig, log: EventLog) -> Dict[str, Any]:
    r"""Plays one AvalonBot game and returns the arena `game_end` payload."""
    adapter = ArenaGraphAdapter(merlin_graph=False)
    bridge = EventBridge(log, adapter)
    agents = build_agents(setup, cfg, log)
    roles = {seat: ARENA_ROLES[name] for seat, name in enumerate(setup.role_names)}

    bridge.emit(
        "game_start",
        seed=setup.seed,
        config_hash=cfg.config_hash(),
        condition=cfg.condition,
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
        seat: {"edges": len(m.graph.edges), "p_evil": dict(m.beliefs.p_evil) if m.beliefs else None}
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
        })
    return {
        "status": "completed",
        "winner": "good" if good_won else "evil",
        "reason": reason,
        "condition": cfg.condition,
        "quest_results": list(runner.engine.quest_results),
        "proposals": len(runner.engine.vote_history),
        "merlin_survived": metrics.merlin_survived,
        "belief_paths": metrics.belief_paths,
        "seats": seats,
    }
