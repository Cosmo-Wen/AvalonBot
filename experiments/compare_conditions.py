r"""Paired comparison of the ablation conditions, from their run dirs. Writes the committed results.

Game i has the same deal in every condition (see paired_seeds.py), so each seed is one pair and
binary outcomes are compared with an exact McNemar test on the discordant pairs.

    python experiments/compare_conditions.py --runs runs/sol --out experiments/sol-ablation-2026-10-24
"""
import argparse
import csv
import glob
import json
import os
import shutil
import sys
from itertools import combinations
from math import comb

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arena.__main__ import summarize  # noqa: E402
from arena.events import read_events  # noqa: E402

CONDITIONS = {"A": "chat_only", "B": "belief_graph", "C": "rule_graph"}


def game_row(path):
    events = read_events(path)
    if not events or events[-1]["type"] != "game_end":
        return None
    end = events[-1]["data"]
    start = next(e["data"] for e in events if e["type"] == "game_start")
    quests = [e["data"] for e in events if e["type"] == "quest_result"]
    calls = [e["data"] for e in events if e["type"] == "llm_call"]
    paths = next((e["data"]["belief_paths"] for e in events if e["type"] == "beliefs"), {}) or {}
    path_counts = {}
    for per_seat in paths.values():
        for k, v in per_seat.items():
            path_counts[k] = path_counts.get(k, 0) + v
    servant_acc = [s["deduction_acc"] for s in end["seats"]
                   if s["role"] == "Servant" and s.get("deduction_acc") is not None]
    return {
        "game_idx": events[-1]["game_idx"],
        "roles": "/".join(s["role"] for s in start["seats"]),
        "quest_leader": start["quest_leader"],
        "winner": end["winner"],
        "reason": end["reason"],
        "good_win": end["winner"] == "good",
        "three_passed": end["reason"] != "missions",  # good passed 3 quests (then won or lost Merlin)
        "assassinated": end["reason"] == "assassination",
        "quests_passed": sum(q["succeeded"] for q in quests),
        "quests_played": len(quests),
        "calls": len(calls),
        "input_tokens": sum(c.get("input_tokens", 0) for c in calls),
        "output_tokens": sum(c.get("output_tokens", 0) for c in calls),
        "llm_errors": sum(e["type"] == "llm_error" for e in events),
        "retries": sum(e["type"] == "retry" for e in events),
        "belief_paths": path_counts,
        "servant_deduction_acc": round(sum(servant_acc) / len(servant_acc), 4) if servant_acc else None,
    }


def load(run_dir):
    rows = {}
    for path in sorted(glob.glob(os.path.join(run_dir, "games", "game_*.jsonl"))):
        if ".partial." in path:
            continue
        row = game_row(path)
        if row is not None:
            rows[row["game_idx"]] = row
    return rows


def mcnemar(x, y):
    r"""Exact two-sided McNemar p for paired booleans: (x-only, y-only, p)."""
    x_only = sum(a and not b for a, b in zip(x, y))
    y_only = sum(b and not a for a, b in zip(x, y))
    t = x_only + y_only
    p = 1.0 if t == 0 else min(1.0, 2 * sum(comb(t, j) for j in range(min(x_only, y_only) + 1)) / 2 ** t)
    return x_only, y_only, round(p, 4)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", default="runs/sol")
    parser.add_argument("--out", default="experiments/sol-ablation-2026-10-24")
    args = parser.parse_args(argv)

    data = {k: load(os.path.join(args.runs, d)) for k, d in CONDITIONS.items()
            if os.path.isdir(os.path.join(args.runs, d))}
    pairs = sorted(set.intersection(*(set(r) for r in data.values())))
    for k, rows in data.items():  # same seed, same deal: guard against mixing up run dirs
        assert all(rows[i]["roles"] == data["A"][i]["roles"] for i in pairs), f"{k} deals differ from A"
    os.makedirs(args.out, exist_ok=True)

    per_condition = {}
    for k, rows in data.items():
        g = [rows[i] for i in pairs]
        three = [r for r in g if r["three_passed"]]
        acc = [r["servant_deduction_acc"] for r in g if r["servant_deduction_acc"] is not None]
        paths = {}
        for r in g:
            for p, v in r["belief_paths"].items():
                paths[p] = paths.get(p, 0) + v
        per_condition[k] = {
            "condition": CONDITIONS[k],
            "games": len(g),
            "good_wins": sum(r["good_win"] for r in g),
            "three_quests_passed": len(three),
            "merlin_assassinated_after_three": sum(r["assassinated"] for r in three),
            "mean_quests_passed": round(sum(r["quests_passed"] for r in g) / len(g), 3),
            "servant_deduction_acc": round(sum(acc) / len(acc), 4) if acc else None,
            "belief_paths": paths,
            "calls": sum(r["calls"] for r in g),
            "input_tokens": sum(r["input_tokens"] for r in g),
            "output_tokens": sum(r["output_tokens"] for r in g),
            "llm_errors": sum(r["llm_errors"] for r in g),
            "games_with_errors": [r["game_idx"] for r in g if r["llm_errors"]],
        }

    paired = {}
    for x, y in combinations(sorted(data), 2):
        paired[f"{x}_vs_{y}"] = {}
        for metric in ("good_win", "three_passed", "assassinated"):
            xo, yo, p = mcnemar([data[x][i][metric] for i in pairs], [data[y][i][metric] for i in pairs])
            paired[f"{x}_vs_{y}"][metric] = {f"{x}_only": xo, f"{y}_only": yo, "mcnemar_exact_p": p}
        diffs = [data[y][i]["quests_passed"] - data[x][i]["quests_passed"] for i in pairs]
        paired[f"{x}_vs_{y}"]["quests_passed"] = {
            f"mean_{y}_minus_{x}": round(sum(diffs) / len(diffs), 3),
            f"{y}_more": sum(d > 0 for d in diffs), f"{x}_more": sum(d < 0 for d in diffs),
            "ties": sum(d == 0 for d in diffs)}

    with open(os.path.join(args.out, "comparison.json"), "w") as f:
        json.dump({"pairs": len(pairs), "conditions": per_condition, "paired": paired}, f, indent=1)

    fields = ["winner", "reason", "quests_passed", "calls", "input_tokens", "output_tokens", "llm_errors",
              "retries", "servant_deduction_acc", "belief_paths"]
    with open(os.path.join(args.out, "pairs.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["game_idx", "roles", "quest_leader"] + [f"{k}_{c}" for k in sorted(data) for c in fields])
        for i in pairs:
            a = data["A"][i]
            w.writerow([i, a["roles"], a["quest_leader"]] + [
                json.dumps(data[k][i][c]) if c == "belief_paths" else data[k][i][c]
                for k in sorted(data) for c in fields])

    for k, d in CONDITIONS.items():
        run_dir = os.path.join(args.runs, d)
        if not os.path.isdir(run_dir):
            continue
        with open(os.path.join(args.out, f"summary_{d}.json"), "w") as f:
            json.dump(summarize(run_dir), f, indent=1)
        shutil.copy(os.path.join(run_dir, "manifest.json"), os.path.join(args.out, f"manifest_{d}.json"))

    print(json.dumps({"pairs": len(pairs), "conditions": {k: {m: v[m] for m in (
        "good_wins", "three_quests_passed", "merlin_assassinated_after_three", "mean_quests_passed",
        "llm_errors")} for k, v in per_condition.items()}, "paired": paired}, indent=1))


if __name__ == "__main__":
    main()
