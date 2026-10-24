import hashlib
import json
import os
from typing import List, Literal, Optional

import yaml
from pydantic import BaseModel, validator, root_validator

NUM_PLAYERS = 5
# model used when a seat doesn't name one
DEFAULT_MODELS = {"claude_cli": "sonnet", "anthropic": "claude-opus-5-5", "openai": "gpt-6.1-sol", "fake": "fake"}
VALID_ROLES = {"Merlin", "Percival", "Morgana", "Mordred", "Oberon", "Servant", "Minion", "Assassin"}
EVIL_ROLES = {"Morgana", "Mordred", "Oberon", "Minion", "Assassin"}

# fields that can change between resumes without affecting game outcomes
NON_SEMANTIC_FIELDS = {"concurrency", "num_games", "claude_bin", "cli_max_parallel", "llm_timeout_s",
                       "max_inflight_requests",
                       "llm_max_retries", "max_game_retries", "backoff_base_s", "backoff_max_s"}


class SeatSpec(BaseModel):
    r"""One participant in the game. Seat shuffling permutes these across seats."""
    agent: Literal["llm"] = "llm"
    # openai: an OpenAI-compatible endpoint (AvalonBot's LLMAgent); fake: AvalonBot's offline
    # HeuristicAgent. claude_cli and anthropic are text-only backends, usable by play functions
    # that don't need tool calls.
    provider: Literal["claude_cli", "anthropic", "openai", "fake"] = "openai"
    # claude_cli: a Claude Code alias or id (haiku / sonnet / opus); anthropic: an API model id
    # (the aliases haiku / sonnet / opus also work). Defaults per provider: DEFAULT_MODELS.
    model: Optional[str] = None
    effort: Optional[Literal["low", "medium", "high", "xhigh", "max"]] = "medium"  # reasoning effort; null to omit
    name: Optional[str] = None           # stable participant id; defaults to "<agent>:<model>#<index>"


class ArenaConfig(BaseModel):
    num_players: int = NUM_PLAYERS
    seats: List[SeatSpec]
    roles: List[str] = ["Merlin", "Servant", "Servant", "Assassin", "Minion"]

    num_games: int = 1
    base_seed: int = 0
    shuffle_roles: bool = True
    shuffle_seats: bool = True
    random_leader: bool = True
    # AvalonBot condition for the good team; the evil team always plays chat-only (A)
    condition: Literal["chat_only", "belief_graph", "rule_graph"] = "chat_only"
    play_fn: str = "avalon.arena_play:play_game"  # "module:function" that plays one game

    concurrency: int = 1
    max_game_retries: int = 2
    llm_max_retries: int = 5
    llm_timeout_s: float = 180.0
    claude_bin: Optional[str] = None     # path to the Claude Code CLI; defaults to `claude` on PATH
    cli_max_parallel: int = 2            # max concurrent `claude -p` processes across all games
    max_inflight_requests: int = 6       # max concurrent model API requests across all games (gateways cap this)
    api_max_tokens: int = 16000          # anthropic / openai: max output tokens per request
    # openai: any OpenAI-compatible endpoint; the key is read from OPENAI_API_KEY and never logged
    openai_base_url: Optional[str] = None  # defaults to OPENAI_BASE_URL, then api.openai.com
    backoff_base_s: float = 2.0
    backoff_max_s: float = 60.0

    @validator("num_players")
    def _five_players(cls, v):
        if v != NUM_PLAYERS:
            raise ValueError(f"only {NUM_PLAYERS}-player games are supported")
        return v

    @validator("roles")
    def _valid_roles(cls, v):
        unknown = set(v) - VALID_ROLES
        if unknown:
            raise ValueError(f"unknown roles: {sorted(unknown)}")
        if v.count("Assassin") != 1:
            raise ValueError("exactly one Assassin is required")
        if sum(r in EVIL_ROLES for r in v) != 2:
            raise ValueError("a 5-player game needs exactly 2 evil roles")
        return v

    @root_validator(skip_on_failure=True)
    def _sizes_and_names(cls, values):
        n = values["num_players"]
        if len(values["seats"]) != n:
            raise ValueError(f"expected {n} seats, got {len(values['seats'])}")
        if len(values["roles"]) != n:
            raise ValueError(f"expected {n} roles, got {len(values['roles'])}")
        for i, seat in enumerate(values["seats"]):
            if seat.model is None:
                seat.model = DEFAULT_MODELS[seat.provider]
            if seat.name is None:
                seat.name = f"{seat.agent}:{seat.model}#{i}"
        names = [s.name for s in values["seats"]]
        if len(set(names)) != len(names):
            raise ValueError(f"seat names must be unique: {names}")
        return values

    def config_hash(self) -> str:
        semantic = self.dict(exclude=NON_SEMANTIC_FIELDS)
        blob = json.dumps(semantic, sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:16]


def load_env_file(path: str = ".env") -> list:
    r"""Load KEY=VALUE lines from a local secrets file into os.environ, without overriding variables
    that are already set. Returns the names loaded (never the values)."""
    if not os.path.exists(path):
        return []
    loaded = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name, value = name.strip().removeprefix("export ").strip(), value.strip().strip("'\"")
            if name and name not in os.environ:
                os.environ[name] = value
                loaded.append(name)
    return loaded


def load_config(path: str) -> ArenaConfig:
    with open(path, encoding="utf-8") as f:
        return ArenaConfig.parse_obj(yaml.safe_load(f))
