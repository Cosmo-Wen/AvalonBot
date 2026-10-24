r"""Show how condition-B beliefs move across quests, from a run dir's game logs.

Condition B's extraction runs once per quest, at that quest's discussion, so the P(evil) a seat
reports at quest k+1 is its first belief after quest k's result. For each failed quest this prints
every good seat's P(evil) before and after, and whether the failed team's members rose.

The P(evil) shown is what the model returned (`record_observations`), taking the retry's answer when
the first was rejected. When both were rejected the seat fell back to the pair-counting rule; the
`belief_paths` summary at game end counts how often that happened.

    python experiments/belief_moves.py runs/smoke-B
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arena.events import read_events  # noqa: E402


def extraction_beliefs(events):
    r"""{seat: {quest: p_evil}}: the last record_observations p_evil each seat gave in each quest."""
    out, quest = {}, 0
    for e in events:
        d = e["data"]
        if e["type"] == "discussion":
            quest = d["quest"]
        if e["type"] != "llm_call":
            continue
        for call in d.get("tool_calls") or []:
            if call["name"] != "record_observations":
                continue
            try:
                args = json.loads(call["arguments"] or "{}")
            except json.JSONDecodeError:
                continue
            if args.get("p_evil"):
                out.setdefault(d["seat"], {})[quest] = {int(k): float(v) for k, v in args["p_evil"].items()}
    return out


def fmt(p):
    return " ".join(f"#{k}:{v:.2f}" for k, v in sorted(p.items()))


def report(path):
    events = read_events(path)
    start = next(e["data"] for e in events if e["type"] == "game_start")
    roles = {s["seat"]: s["role"] for s in start["seats"]}
    beliefs = extraction_beliefs(events)
    results = [e["data"] for e in events if e["type"] == "quest_result"]
    end = events[-1]["data"] if events[-1]["type"] == "game_end" else {}
    paths = next((e["data"]["belief_paths"] for e in events if e["type"] == "beliefs"), {})
    print(f"== {os.path.basename(path)}  roles {roles}  winner {end.get('winner')} ({end.get('reason')})")
    print("   quests: " + ", ".join(f"Q{r['quest'] + 1} {sorted(r['team'])} {'ok' if r['succeeded'] else 'FAIL'}"
                                    for r in results))
    print(f"   belief paths: {paths}")
    moved = 0
    for r in results:
        if r["succeeded"]:
            continue
        q, team = r["quest"], set(r["team"])
        for seat, by_q in sorted(beliefs.items()):
            before, after = by_q.get(q), by_q.get(q + 1)
            if after is None:
                print(f"   Q{q + 1} FAIL, seat {seat} ({roles[seat]}): no belief after (game ended)")
                continue
            before = before or {k: 0.5 for k in after}
            # a seat on the failed team may clear one teammate and blame another, so judge the team's
            # P(evil) mass and whether its top suspect is on the team, not every member's change
            others = [p for p in team if p in after]
            mass_before, mass_after = sum(before.get(p, 0.5) for p in others), sum(after[p] for p in others)
            top_on_team = max(after, key=after.get) in team
            ok = mass_after > mass_before and top_on_team
            moved += ok
            print(f"   Q{q + 1} FAIL team {sorted(team)}, seat {seat} ({roles[seat]}): "
                  f"{fmt(before)}  ->  {fmt(after)}   team mass {mass_before:.2f}->{mass_after:.2f}, "
                  f"top suspect on team: {'yes' if top_on_team else 'no'}  {'ok' if ok else 'check by hand'}")
    return moved


if __name__ == "__main__":
    for path in sorted(glob.glob(os.path.join(sys.argv[1], "games", "game_*.jsonl"))):
        if ".partial." not in path:
            report(path)
