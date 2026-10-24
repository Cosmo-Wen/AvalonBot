from typing import List

import numpy as np
from pydantic import BaseModel

from .config import ArenaConfig, SeatSpec

# order matters: each name gets its own child stream of SeedSequence([base_seed, game_idx])
STREAMS = ("roles", "seats", "leader", "agents")


class GameSetup(BaseModel):
    game_idx: int
    seed: List[int]                 # SeedSequence entropy: [base_seed, game_idx]
    seat_specs: List[SeatSpec]      # participant sitting at each seat
    seat_participants: List[int]    # index into cfg.seats for each seat
    role_names: List[str]           # role at each seat
    quest_leader: int
    agent_seeds: List[int]          # per-seat seed for agent-internal RNG

    def presets(self) -> dict:
        r"""Presets accepted by `AvalonGameEnvironment.from_presets`."""
        return {
            "num_players": len(self.role_names),
            "quest_leader": self.quest_leader,
            "role_names": list(self.role_names),
        }


def game_streams(base_seed: int, game_idx: int) -> dict:
    children = np.random.SeedSequence([base_seed, game_idx]).spawn(len(STREAMS))
    return {name: np.random.default_rng(child) for name, child in zip(STREAMS, children)}


def deal(cfg: ArenaConfig, game_idx: int) -> GameSetup:
    r"""Deterministically derive a game's setup from (base_seed, game_idx).

    Role, seat, leader and agent streams are independent, so toggling one shuffle
    never changes the outcome of another.
    """
    rng = game_streams(cfg.base_seed, game_idx)
    n = cfg.num_players

    role_names = list(cfg.roles)
    role_perm = rng["roles"].permutation(n)
    if cfg.shuffle_roles:
        role_names = [role_names[i] for i in role_perm]

    seat_perm = rng["seats"].permutation(n)
    participants = [int(i) for i in seat_perm] if cfg.shuffle_seats else list(range(n))

    leader = int(rng["leader"].integers(0, n))
    if not cfg.random_leader:
        leader = 0

    agent_seeds = [int(s) for s in rng["agents"].integers(0, 2**31 - 1, size=n)]

    return GameSetup(
        game_idx=game_idx,
        seed=[cfg.base_seed, game_idx],
        seat_specs=[cfg.seats[p] for p in participants],
        seat_participants=participants,
        role_names=role_names,
        quest_leader=leader,
        agent_seeds=agent_seeds,
    )
