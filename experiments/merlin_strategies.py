r"""Compare Merlin strategies against a baseline run on the same seeds, from game logs (no model calls).

For each run: outcomes, each good player's team-vote accuracy against the true roles, how often
Merlin is the most accurate voter, and the *kind* of wrong votes Merlin and the Servants make
(approving a team with evil on it vs rejecting a clean one). A Merlin hidden among Servants should
err like they do.

Assassin hits are compared with an exact McNemar test only on seeds where both runs passed 3 quests,
since the Assassin only acts then.

    python experiments/merlin_strategies.py --baseline runs/haiku/rule_graph \
        runs/haiku/rule_graph_cover runs/haiku/rule_graph_cap_v1 runs/haiku/rule_graph_cap --seeds 0-9
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arena.events import read_events  # noqa: E402
from experiments.compare_conditions import mcnemar  # noqa: E402

EVIL = ("Assassin", "Minion")


def game_stats(events):
    end = events[-1]["data"]
    roles = {s["seat"]: s["role"] for s in events[0]["data"]["seats"]}
    evil = {s for s, r in roles.items() if r in EVIL}
    merlin = next(s for s, r in roles.items() if r == "Merlin")
    good = [s for s in roles if s not in evil]
    team, votes = None, {s: {"right": 0, "approved_evil": 0, "rejected_clean": 0} for s in good}
    for e in events:
        if e["type"] == "team_proposed":
            team = set(e["data"]["team"])
        elif e["type"] == "team_votes":
            clean = not team & evil
            for s in good:
                approve = bool(e["data"]["votes"][s])
                if approve == clean:
                    votes[s]["right"] += 1
                elif approve:
                    votes[s]["approved_evil"] += 1
                else:
                    votes[s]["rejected_clean"] += 1
    acc = {s: v["right"] / max(1, sum(v.values())) for s, v in votes.items()}
    best = max(acc.values())
    return {
        "game_idx": events[-1]["game_idx"], "merlin": merlin, "votes": votes, "acc": acc,
        "merlin_top": acc[merlin] == best, "merlin_sole_top": [s for s in good if acc[s] == best] == [merlin],
        "good_win": end["winner"] == "good", "three_passed": end["reason"] != "missions",
        "assassinated": end["reason"] == "assassination",
    }


def load(run_dir, seeds):
    out = {}
    for path in sorted(glob.glob(os.path.join(run_dir, "games", "game_*.jsonl"))):
        if ".partial." in path:
            continue
        events = read_events(path)
        if events and events[-1]["type"] == "game_end" and events[-1]["game_idx"] in seeds:
            out[events[-1]["game_idx"]] = game_stats(events)
    return out


def summary(games):
    g = list(games.values())
    three = [x for x in g if x["three_passed"]]

    def errors(who):
        ae = sum(x["votes"][s]["approved_evil"] for x in g for s in x["votes"] if who(x, s))
        rc = sum(x["votes"][s]["rejected_clean"] for x in g for s in x["votes"] if who(x, s))
        return {"approved_evil": ae, "rejected_clean": rc,
                "approved_evil_share": round(ae / (ae + rc), 3) if ae + rc else None}

    def mean_acc(who):
        xs = [x["acc"][s] for x in g for s in x["acc"] if who(x, s)]
        return round(sum(xs) / len(xs), 3) if xs else None

    is_merlin = lambda x, s: s == x["merlin"]  # noqa: E731
    is_servant = lambda x, s: s != x["merlin"]  # noqa: E731
    return {
        "games": len(g), "good_wins": sum(x["good_win"] for x in g), "three_passed": len(three),
        "assassinated_after_three": sum(x["assassinated"] for x in three),
        "merlin_top_voter": sum(x["merlin_top"] for x in g), "merlin_sole_top_voter": sum(x["merlin_sole_top"] for x in g),
        "vote_accuracy": {"merlin": mean_acc(is_merlin), "servants": mean_acc(is_servant)},
        "vote_errors": {"merlin": errors(is_merlin), "servants": errors(is_servant)},
    }


def paired(base, run):
    seeds = sorted(set(base) & set(run))
    both3 = [i for i in seeds if base[i]["three_passed"] and run[i]["three_passed"]]
    out = {"pairs": len(seeds), "both_passed_three": len(both3)}
    for metric, over in (("good_win", seeds), ("three_passed", seeds), ("assassinated", both3)):
        b_only, r_only, p = mcnemar([base[i][metric] for i in over], [run[i][metric] for i in over])
        out[metric] = {"baseline_only": b_only, "run_only": r_only, "mcnemar_exact_p": p,
                       "baseline": sum(base[i][metric] for i in over), "run": sum(run[i][metric] for i in over), "n": len(over)}
    return out


def parse_seeds(text):
    lo, _, hi = text.partition("-")
    return set(range(int(lo), int(hi or lo) + 1))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("runs", nargs="+")
    parser.add_argument("--seeds", default="0-39")
    parser.add_argument("--out", help="write the result as JSON here")
    args = parser.parse_args(argv)
    seeds = parse_seeds(args.seeds)
    base = load(args.baseline, seeds)
    result = {"seeds": args.seeds, "baseline": {"run": args.baseline, **summary(base)}, "runs": {}}
    for run_dir in args.runs:
        games = load(run_dir, seeds)
        result["runs"][run_dir] = {**summary(games), "vs_baseline": paired(base, games)}
    text = json.dumps(result, indent=1)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
    print(text)


if __name__ == "__main__":
    main()
