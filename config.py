import hashlib
import json
from typing import List, Literal, Optional

import yaml
from pydantic import BaseModel, validator, root_validator

NUM_PLAYERS = 5
# model used when a seat doesn't name one
DEFAULT_MODELS = {"claude_cli": "sonnet", "anthropic": "claude-opus-5-5", "fake": "fake"}
VALID_ROLES = {"Merlin", "Percival", "Morgana", "Mordred", "Oberon", "Servant", "Minion", "Assassin"}
EVIL_ROLES = {"Morgana", "Mordred", "Oberon", "Minion", "Assassin"}

# fields that can change between resumes without affecting game outcomes
NON_SEMANTIC_FIELDS = {"concurrency", "num_games", "claude_bin", "cli_max_parallel", "llm_timeout_s",
                       "llm_max_retries", "max_game_retries", "backoff_base_s", "backoff_max_s"}


class SeatSpec(BaseModel):
    r"""One participant in the game. Seat shuffling permutes these across seats."""
    agent: Literal["llm", "search", "recon"]
    provider: Literal["claude_cli", "anthropic", "fake"] = "claude_cli"
    # claude_cli: a Claude Code alias or id (haiku / sonnet / opus); anthropic: an API model id
    # (the aliases haiku / sonnet / opus also work). Defaults per provider: DEFAULT_MODELS.
    model: Optional[str] = None
    effort: Optional[Literal["low", "medium", "high", "xhigh", "max"]] = "medium"  # reasoning effort; null to omit
    planner_model: Optional[str] = None  # search/recon planner's model; defaults to `model`
    planner_num_rollout: int = 100       # search/recon MCTS rollouts per decision (CPU-bound)
    planner_node_budget: int = 100       # search/recon MCTS node budget per decision
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
    discussion: bool = True
    reply_max_words: Optional[int] = None  # ask every player to keep replies under this many words

    concurrency: int = 1
    max_game_retries: int = 2
    llm_max_retries: int = 5
    llm_timeout_s: float = 180.0
    claude_bin: Optional[str] = None     # path to the Claude Code CLI; defaults to `claude` on PATH
    cli_max_parallel: int = 2            # max concurrent `claude -p` processes across all games
    api_max_tokens: int = 16000          # anthropic: max_tokens per request
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


def load_config(path: str) -> ArenaConfig:
    with open(path, encoding="utf-8") as f:
        return ArenaConfig.parse_obj(yaml.safe_load(f))
