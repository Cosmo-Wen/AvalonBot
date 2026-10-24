from collections import Counter

import pytest

from arena.config import ArenaConfig
from arena.seeding import deal

from .conftest import make_cfg


def test_same_seed_same_deal(cfg):
    assert deal(cfg, 3) == deal(cfg, 3)
    assert deal(cfg, 3) == deal(make_cfg(), 3)


def test_deals_vary_across_games(cfg):
    deals = [deal(cfg, i) for i in range(30)]
    assert len({tuple(d.role_names) for d in deals}) > 1
    assert len({tuple(d.seat_participants) for d in deals}) > 1
    assert len({d.quest_leader for d in deals}) > 1


def test_base_seed_changes_deal(cfg):
    other = make_cfg(base_seed=8)
    assert [deal(cfg, i).role_names for i in range(10)] != [deal(other, i).role_names for i in range(10)]


def test_role_multiset_and_ranges(cfg):
    for i in range(30):
        d = deal(cfg, i)
        assert Counter(d.role_names) == Counter(cfg.roles)
        assert sorted(d.seat_participants) == list(range(5))
        assert 0 <= d.quest_leader < 5
        assert [s.name for s in d.seat_specs] == [cfg.seats[p].name for p in d.seat_participants]


def test_shuffles_are_independent(cfg):
    no_seats = make_cfg(shuffle_seats=False)
    no_roles = make_cfg(shuffle_roles=False)
    for i in range(10):
        full = deal(cfg, i)
        assert deal(no_seats, i).role_names == full.role_names
        assert deal(no_seats, i).seat_participants == list(range(5))
        assert deal(no_roles, i).seat_participants == full.seat_participants
        assert deal(no_roles, i).role_names == cfg.roles
        assert deal(no_roles, i).quest_leader == full.quest_leader


def test_fixed_leader():
    cfg = make_cfg(random_leader=False)
    assert {deal(cfg, i).quest_leader for i in range(10)} == {0}


def test_presets_shape(cfg):
    p = deal(cfg, 0).presets()
    assert p["num_players"] == 5 and len(p["role_names"]) == 5


@pytest.mark.parametrize("bad", [
    dict(num_players=6),
    dict(seats=[{"agent": "llm"}] * 4),
    dict(roles=["Merlin", "Servant", "Servant", "Minion", "Minion"]),
    dict(roles=["Merlin", "Servant", "Servant", "Servant", "Assassin"]),
    dict(seats=[{"agent": "llm", "name": "x"}] * 5),
])
def test_invalid_config(bad):
    with pytest.raises(ValueError):
        make_cfg(**bad)


def test_config_hash_ignores_non_semantic_fields(cfg):
    assert cfg.config_hash() == make_cfg(concurrency=10, num_games=100).config_hash()
    assert cfg.config_hash() != make_cfg(base_seed=1).config_hash()
