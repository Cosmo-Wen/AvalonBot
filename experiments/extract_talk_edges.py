r"""Pull the talk edges each player extracted during a batch game out of its log, for avalon.visualize.

Condition B and C servants call `record_observations` after each discussion; the edges they return
cite utterances by the live runner's `#n` numbers, which differ from the log's `seq`. The extraction
prompts list every cited utterance as `#n [Qx.y] Pk: "text"`, so each `#n` is matched to the log's
`discussion` event with the same speaker and text. Each edge keeps its extractor as `owner`, so a
replay adds it to that player's graph only.

    python experiments/extract_talk_edges.py runs/sol/belief_graph/games/game_00000.jsonl -o edges.json
    python -m avalon.visualize runs/sol/belief_graph/games/game_00000.jsonl edges.json -o game0.html
"""
import argparse
import json
import re
import sys

LINE = re.compile(r'^#(\d+) \[Q\d+\.\d+\] P(\d+): "(.*)"$', re.M)


def extract(events):
    log_seq = {}  # (seat, text) -> log seq of that discussion event
    for e in events:
        if e["type"] == "discussion":
            log_seq.setdefault((e["data"]["seat"], e["data"]["text"].strip()), e["seq"])
    live_seq = {}  # runner #n -> log seq
    edges, dropped = [], 0
    for e in events:
        if e["type"] != "llm_call":
            continue
        for n, seat, text in LINE.findall(e["data"].get("prompt", "")):
            seq = log_seq.get((int(seat), text.strip()))
            if seq is not None:
                live_seq[int(n)] = seq
        for call in e["data"].get("tool_calls") or []:
            if call["name"] != "record_observations":
                continue
            try:
                args = json.loads(call["arguments"] or "{}")
            except json.JSONDecodeError:
                continue
            for raw in args.get("edges") or []:
                try:
                    sources = [live_seq[int(s)] for s in raw.get("sources") or []]
                except (KeyError, TypeError, ValueError):
                    sources = []
                if not sources:
                    dropped += 1
                    continue
                edges.append(dict(raw, sources=sources, owner=e["data"]["seat"]))
    return edges, dropped


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("game")
    parser.add_argument("-o", "--out", required=True)
    args = parser.parse_args(argv)
    with open(args.game, encoding="utf-8") as f:
        events = [json.loads(line) for line in f if line.strip()]
    edges, dropped = extract(events)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"about": f"Talk edges extracted live during {args.game}; sources are log seq numbers.",
                   "edges": edges}, f, indent=1)
    print(f"{len(edges)} edges from {len({e['owner'] for e in edges})} players -> {args.out}"
          + (f" ({dropped} dropped: cited utterances not found)" if dropped else ""), file=sys.stderr)


if __name__ == "__main__":
    main()
