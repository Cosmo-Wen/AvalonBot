r"""Paired comparison of the Percival conditions P0 (chat_only) and P1 (four_world), from their run dirs.

Game i has the same deal in both runs, so each seed is one pair. Fixed before the 40-pair Haiku batch:
- Primary: good-team win, exact McNemar test on the discordant pairs.
- Secondary: good passed 3 quests; the Assassin hit Merlin, on pairs where both games reached the
  assassination; Merlin's vote-accuracy rank among the good players (1 = most accurate, so most exposed).

    python experiments/compare_percival.py --runs runs/haiku-percival --out experiments/percival-haiku-2026-10-25
"""
import argparse
import csv
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arena.__main__ import summarize  # noqa: E402
from arena.events import read_events  # noqa: E402
from experiments.compare_conditions import mcnemar  # noqa: E402

CONDITIONS = {"P0": "p0", "P1": "p1"}


def game_row(path):
    events = read_events(path)
    if not events or events[-1]["type"] != "game_end":
        return None
    end = events[-1]["data"]
    start = next(e["data"] for e in events if e["type"] == "game_start")
    metrics = end.get("percival_metrics") or {}
    calls = [e["data"] for e in events if e["type"] == "llm_call"]
    return {
        "game_idx": events[-1]["game_idx"],
        "roles": "/".join(s["role"] for s in start["seats"]),
        "winner": end["winner"],
        "reason": end["reason"],
        "good_win": end["winner"] == "good",
        "three_passed": end["reason"] != "missions",
        "assassination_reached": bool(metrics.get("assassination_reached")),
        "assassin_hit": bool(metrics.get("assassin_hit")),
        "merlin_rank": metrics.get("merlin_vote_accuracy_rank"),
        "p_true_merlin": metrics.get("p_true_merlin"),
        "calls": len(calls),
        "llm_errors": sum(e["type"] == "llm_error" for e in events),
    }


def load(run_dir):
    rows = {}
    for path in sorted(os.listdir(os.path.join(run_dir, "games"))):
        if path.startswith("game_") and path.endswith(".jsonl") and ".partial." not in path:
            row = game_row(os.path.join(run_dir, "games", path))
            if row is not None:
                rows[row["game_idx"]] = row
    return rows


def mean(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 4) if values else None


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", default="runs/haiku-percival")
    parser.add_argument("--out", default="experiments/percival-haiku-2026-10-25")
    args = parser.parse_args(argv)

    data = {k: load(os.path.join(args.runs, d)) for k, d in CONDITIONS.items()}
    pairs = sorted(set(data["P0"]) & set(data["P1"]))
    assert all(data["P0"][i]["roles"] == data["P1"][i]["roles"] for i in pairs), "P0 and P1 deals differ"
    os.makedirs(args.out, exist_ok=True)

    per_condition = {}
    for k, rows in data.items():
        g = [rows[i] for i in pairs]
        reached = [r for r in g if r["assassination_reached"]]
        per_condition[k] = {
            "condition": CONDITIONS[k], "games": len(g),
            "good_wins": sum(r["good_win"] for r in g),
            "three_quests_passed": sum(r["three_passed"] for r in g),
            "assassinations": len(reached), "assassin_hits": sum(r["assassin_hit"] for r in reached),
            "merlin_mean_vote_rank": mean(r["merlin_rank"] for r in g),
            "mean_p_true_merlin": mean(r["p_true_merlin"] for r in g),
            "calls": sum(r["calls"] for r in g), "llm_errors": sum(r["llm_errors"] for r in g),
            "games_with_errors": [r["game_idx"] for r in g if r["llm_errors"]],
        }

    both_reached = [i for i in pairs if data["P0"][i]["assassination_reached"] and data["P1"][i]["assassination_reached"]]
    paired = {}
    for metric, idx in (("good_win", pairs), ("three_passed", pairs), ("assassin_hit", both_reached)):
        p0_only, p1_only, p = mcnemar([data["P0"][i][metric] for i in idx], [data["P1"][i][metric] for i in idx])
        paired[metric] = {"pairs": len(idx), "P0_only": p0_only, "P1_only": p1_only, "mcnemar_exact_p": p}
    ranked = [i for i in pairs if data["P0"][i]["merlin_rank"] is not None and data["P1"][i]["merlin_rank"] is not None]
    diffs = [data["P1"][i]["merlin_rank"] - data["P0"][i]["merlin_rank"] for i in ranked]
    paired["merlin_rank"] = {"pairs": len(ranked), "mean_P1_minus_P0": mean(diffs),
                             "P1_higher": sum(d > 0 for d in diffs), "P0_higher": sum(d < 0 for d in diffs),
                             "ties": sum(d == 0 for d in diffs)}

    with open(os.path.join(args.out, "comparison.json"), "w") as f:
        json.dump({"pairs": len(pairs), "conditions": per_condition, "paired": paired}, f, indent=1)
    fields = ["winner", "reason", "assassin_hit", "merlin_rank", "p_true_merlin", "calls", "llm_errors"]
    with open(os.path.join(args.out, "pairs.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["game_idx", "roles"] + [f"{k}_{c}" for k in CONDITIONS for c in fields])
        for i in pairs:
            w.writerow([i, data["P0"][i]["roles"]] + [data[k][i][c] for k in CONDITIONS for c in fields])
    for d in CONDITIONS.values():
        run_dir = os.path.join(args.runs, d)
        with open(os.path.join(args.out, f"summary_{d}.json"), "w") as f:
            json.dump(summarize(run_dir), f, indent=1)
        shutil.copy(os.path.join(run_dir, "manifest.json"), os.path.join(args.out, f"manifest_{d}.json"))

    print(json.dumps({"pairs": len(pairs), "conditions": per_condition, "paired": paired}, indent=1))


if __name__ == "__main__":
    main()
