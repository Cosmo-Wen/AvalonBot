r"""Does Merlin's vote record give them away? Offline, from existing game logs (no model calls).

The Assassin knows who is evil, so it can grade every good player's team votes against the truth: a
vote is correct if it approves a team with no evil on it or rejects a team with evil on it. Servants
vote on public evidence; Merlin votes on what they saw. If the Assassin reads votes, the most accurate
voter should usually be Merlin, about as often as the Assassin hits Merlin.

For each game with an assassination this reports every good player's vote accuracy, Merlin's rank,
what a pure vote-grading Assassin would hit (ties split evenly), and what the real Assassin's stated
reason cites.

    python experiments/merlin_vote_leak.py runs/sol/rule_graph [runs/sol/belief_graph ...]
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arena.events import read_events  # noqa: E402

CUES = {
    "votes": r"\bvot|approv|reject|support(?:ed|s)? (?:all-good|clean|the) team",
    "proposals": r"propos|picked|chose|leader|selected",
    "speech": r"\bsaid\b|accus|defend|claim|suspect|argued|question|speech|identif|pointed|named",
    "quest results": r"\bfail|sabotag|passed|success",
}


def vote_records(events, evil):
    r"""{seat: [correct, ...]} over every team vote, in order."""
    teams, records = {}, {}
    for e in events:
        d = e["data"]
        if e["type"] == "team_proposed":
            teams[(d["quest"], d["round"])] = set(d["team"])
        elif e["type"] == "team_votes":
            clean = not (teams[(d["quest"], d["round"])] & evil)
            for seat, v in enumerate(d["votes"]):
                records.setdefault(seat, []).append(bool(v) == clean)
    return records


def assassin_reason(events):
    for e in events:
        if e["type"] != "llm_call":
            continue
        for c in e["data"].get("tool_calls") or []:
            if c["name"] == "assassinate":
                try:
                    return json.loads(c["arguments"] or "{}").get("reason") or ""
                except json.JSONDecodeError:
                    return c["arguments"] or ""
    return ""


def analyze(run_dir):
    games = []
    for path in sorted(glob.glob(os.path.join(run_dir, "games", "game_*.jsonl"))):
        if ".partial." in path:
            continue
        events = read_events(path)
        hit = next((e["data"] for e in events if e["type"] == "assassination"), None)
        if hit is None:
            continue
        roles = {s["seat"]: s["role"] for s in events[0]["data"]["seats"]}
        evil = {s for s, r in roles.items() if r in ("Assassin", "Minion")}
        merlin = next(s for s, r in roles.items() if r == "Merlin")
        good = [s for s in roles if s not in evil]
        rec = vote_records(events, evil)
        acc = {s: sum(rec[s]) / len(rec[s]) for s in good}
        best = max(acc.values())
        top = [s for s in good if acc[s] == best]
        reason = assassin_reason(events)
        games.append({
            "game": events[0]["game_idx"], "votes": len(rec[merlin]), "merlin": merlin,
            "acc": acc, "merlin_rank": 1 + sum(acc[s] > acc[merlin] for s in good),
            "merlin_top": merlin in top, "merlin_sole_top": top == [merlin],
            "grader_hit": (1 / len(top)) if merlin in top else 0.0,
            "assassin_hit": bool(hit["hit_merlin"]), "target": hit["target"],
            "target_rank": 1 + sum(acc[s] > acc.get(hit["target"], -1) for s in good),
            "cues": [k for k, rx in CUES.items() if re.search(rx, reason, re.I)], "reason": reason,
        })
    return games


def report(run_dir):
    games = analyze(run_dir)
    n = len(games)
    if not n:
        print(f"{run_dir}: no assassinations")
        return
    servant_acc = [a for g in games for s, a in g["acc"].items() if s != g["merlin"]]
    merlin_acc = [g["acc"][g["merlin"]] for g in games]
    print(f"== {run_dir}: {n} games with an assassination, "
          f"{sum(g['votes'] for g in games) / n:.1f} team votes per player")
    print(f"   vote accuracy: Merlin {sum(merlin_acc) / n:.2f}, Servants {sum(servant_acc) / len(servant_acc):.2f}")
    print(f"   Merlin most accurate voter: {sum(g['merlin_top'] for g in games)}/{n} "
          f"(alone at the top in {sum(g['merlin_sole_top'] for g in games)})")
    print(f"   vote-grading Assassin would hit: {sum(g['grader_hit'] for g in games):.1f}/{n} "
          f"(ties split evenly); real Assassin hit: {sum(g['assassin_hit'] for g in games)}/{n}")
    print(f"   real Assassin's target was a top voter: {sum(g['target_rank'] == 1 for g in games)}/{n}")
    for cue in CUES:
        print(f"   reason cites {cue}: {sum(cue in g['cues'] for g in games)}/{n}")
    for g in games:
        accs = " ".join(f"P{s}{'*' if s == g['merlin'] else ''}:{a:.2f}" for s, a in sorted(g["acc"].items()))
        print(f"   seed {g['game']:2d} [{accs}] Merlin rank {g['merlin_rank']}, "
              f"{'HIT' if g['assassin_hit'] else 'miss'} P{g['target']} | {','.join(g['cues'])}")


if __name__ == "__main__":
    for run_dir in sys.argv[1:]:
        report(run_dir)
