r"""Render every batch game's belief graphs (avalon.visualize) and an index that pairs them by seed.

Each page replays one game into every player's memory, with the talk edges that player extracted
live (extract_talk_edges.py); condition A extracts none, so its graphs hold action edges only.
index.html is a seed x condition table of outcomes linking to each page.

    python experiments/render_graphs.py --runs runs/sol --out runs/sol/graphs
    python experiments/render_graphs.py --games 0 7 --out experiments/sol-ablation-2026-10-24/graphs
"""
import argparse
import glob
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from avalon.replay import load_events  # noqa: E402
from avalon.visualize import build_data, render_html  # noqa: E402
from experiments.extract_talk_edges import extract  # noqa: E402

CONDITIONS = {"A": "chat_only", "B": "belief_graph", "C": "rule_graph"}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", default="runs/sol")
    parser.add_argument("--out", default="runs/sol/graphs")
    parser.add_argument("--games", type=int, nargs="*", help="seeds to render (default: all)")
    args = parser.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)

    table = {}  # seed -> condition -> (page, end)
    for k, cond in CONDITIONS.items():
        for path in sorted(glob.glob(os.path.join(args.runs, cond, "games", "game_*.jsonl"))):
            if ".partial." in path:
                continue
            events = load_events(path)
            if events[-1]["type"] != "game_end":
                continue
            idx = events[-1]["game_idx"]
            if args.games and idx not in args.games:
                continue
            edges, _ = extract(events)
            page = f"{k}_{cond}_game_{idx:05d}.html"
            data = build_data(events, edges, f"{k} {cond}, seed {idx}")
            with open(os.path.join(args.out, page), "w", encoding="utf-8") as f:
                f.write(render_html(data))
            table.setdefault(idx, {})[k] = (page, events[-1]["data"])
            print(f"{page}: {len(edges)} talk edges", file=sys.stderr)

    rows = []
    for idx in sorted(table):
        cells = []
        for k in CONDITIONS:
            if k not in table[idx]:
                cells.append("<td>-</td>")
                continue
            page, end = table[idx][k]
            cls = "good" if end["winner"] == "good" else "evil"
            cells.append(f'<td class="{cls}"><a href="{page}">{end["winner"]}</a>'
                         f'<br><small>{html.escape(end["reason"])}</small></td>')
        rows.append(f"<tr><th>{idx}</th>{''.join(cells)}</tr>")
    head = "".join(f"<th>{k} {c}</th>" for k, c in CONDITIONS.items())
    index = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ablation belief graphs</title>
<style>
:root {{ --bg: #fff; --fg: #1f2328; --line: #d0d7de; --good: #1a7f37; --evil: #cf222e; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg: #0d1117; --fg: #e6edf3; --line: #30363d; --good: #3fb950; --evil: #f85149; }} }}
body {{ background: var(--bg); color: var(--fg); font: 14px/1.4 system-ui, sans-serif; margin: 24px 16px; }}
table {{ border-collapse: collapse; }} th, td {{ border: 1px solid var(--line); padding: 6px 10px; text-align: left; }}
a {{ color: inherit; font-weight: 600; }} .good a {{ color: var(--good); }} .evil a {{ color: var(--evil); }}
small {{ opacity: .7; }}
</style></head><body>
<h1>Belief graphs by seed</h1>
<p>Seed <i>i</i> is the same deal in every condition. Each link replays that game into every player's memory.</p>
<table><tr><th>seed</th>{head}</tr>
{chr(10).join(rows)}
</table></body></html>"""
    with open(os.path.join(args.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(index)
    print(f"{sum(len(v) for v in table.values())} pages + index.html -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
