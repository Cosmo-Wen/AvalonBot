r"""Write the paired seed list for the ablation and check that every condition deals the same games.

Game i is dealt from SeedSequence([base_seed, i]) in every condition, so seed i in A, B and C is the
same deal: roles, first leader and per-seat agent seeds. This script makes that list explicit and
fails if the configs would deal any game differently (a changed base_seed, roles or shuffle flag).

    python experiments/paired_seeds.py                      # configs/arena/sol_*.yaml, their num_games
    python experiments/paired_seeds.py --num-games 60 --out runs/sol/paired_seeds.json
"""
import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arena.config import load_config  # noqa: E402
from arena.seeding import deal  # noqa: E402

CONFIGS = ["configs/arena/sol_chat_only.yaml", "configs/arena/sol_belief_graph.yaml",
           "configs/arena/sol_rule_graph.yaml"]


def deal_row(cfg, idx: int) -> dict:
    s = deal(cfg, idx)
    return {"game_idx": idx, "seed": s.seed, "roles": s.role_names, "quest_leader": s.quest_leader,
            "seat_participants": s.seat_participants, "agent_seeds": s.agent_seeds}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--configs", nargs="+", default=CONFIGS)
    parser.add_argument("--num-games", type=int, help="default: the largest num_games in the configs")
    parser.add_argument("--out", default="configs/arena/paired_seeds_sol.json")
    args = parser.parse_args(argv)

    cfgs = {path: load_config(path) for path in args.configs}
    n = args.num_games or max(c.num_games for c in cfgs.values())
    rows = None
    for path, cfg in cfgs.items():
        these = [deal_row(cfg, i) for i in range(n)]
        if rows is None:
            rows = these
            continue
        diff = [r["game_idx"] for r, t in zip(rows, these) if r != t]
        if diff:
            sys.exit(f"{path} deals games {diff[:10]} differently from {args.configs[0]}; not paired")

    for r in rows:
        r["deal_hash"] = hashlib.sha256(json.dumps(
            {k: r[k] for k in ("roles", "quest_leader", "seat_participants", "agent_seeds")},
            sort_keys=True).encode()).hexdigest()[:12]
    out = {
        "conditions": {cfg.condition: path for path, cfg in cfgs.items()},
        "base_seed": next(iter(cfgs.values())).base_seed,
        "num_games": n,
        "games": rows,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=1)
    print(f"{n} paired seeds, identical across {', '.join(out['conditions'])} -> {args.out}")


if __name__ == "__main__":
    main()
