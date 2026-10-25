import pytest

from arena.config import ArenaConfig


def make_cfg(**overrides) -> ArenaConfig:
    base = dict(
        seats=[{"agent": "llm"} for _ in range(5)],
        num_games=6,
        base_seed=7,
        concurrency=3,
        max_game_retries=2,
        backoff_base_s=0.0,
        backoff_max_s=0.0,
    )
    base.update(overrides)
    return ArenaConfig.model_validate(base)


@pytest.fixture
def cfg():
    return make_cfg()
