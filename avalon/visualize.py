"""
Writes a standalone HTML page that shows each player's memory of a replayed game:
their knowledge graph (talk edges between players, teams with votes and results),
their beliefs over time, the constraints they derived, and the transcript they heard.
A slider steps through the game; every view shows only what that player knew at that point.

Usage: py -3.12 -m avalon.visualize <game.jsonl> [talk_edges.json] [-o out.html]
"""

import json
import os
import sys
from typing import Any, Dict, List, Sequence

from .belief_graph import TALK_EDGES
from .engine import ROLE_NAMES
from .memory import PlayerMemory
from .replay import load_events, load_talk_edges, replay_arena_game


def _snapshot(memory: PlayerMemory) -> Dict[str, Any]:
    if memory.beliefs is not None:
        beliefs = {str(p): round(v, 4) for p, v in memory.beliefs.p_evil.items()}
        consistent = memory.beliefs.consistent
    elif memory.merlin is not None:
        beliefs = {str(p): round(v, 4) for p, v in memory.merlin.p_merlin.items()}
        consistent = True
    else:
        beliefs, consistent = {}, True
    return {
        "edgeCount": len(memory.graph.edges),
        "beliefs": beliefs,
        "consistent": consistent,
        "constraints": memory.graph.render_constraints(),
    }


def _player_data(memory: PlayerMemory, snaps: List[Dict[str, Any]]) -> Dict[str, Any]:
    graph = memory.graph
    seq_of = {}
    for e in memory.log:
        if e.kind in ("proposal", "team_vote", "quest_result"):
            seq_of[(e.kind, e.label)] = e.seq
    teams = [
        {
            "label": t.label, "quest": t.quest, "leader": t.leader, "members": list(t.members),
            "votes": {str(p): v for p, v in t.votes.items()}, "approved": t.approved,
            "fails": t.fails, "success": t.success,
            "proposedSeq": seq_of.get(("proposal", t.label)),
            "voteSeq": seq_of.get(("team_vote", t.label)),
            "resultSeq": seq_of.get(("quest_result", t.label)),
        }
        for t in graph.teams.values()
    ]
    result_seq = {t["quest"]: t["resultSeq"] for t in teams if t["resultSeq"] is not None}
    talk = [
        {"id": e.id, "type": e.type, "src": e.src, "dst": e.dst, "seq": e.seq,
         "quote": e.quote, "sources": e.sources, "role": e.role}
        for e in graph.edges if e.type in TALK_EDGES
    ]
    flags = [
        {"talk": t.id, "vote": v.id, "voteSeq": v.seq, "team": v.dst}
        for t, v in graph.contradictions()
    ]
    if memory.beliefs is not None:
        belief_name = "P(evil)"
    elif memory.merlin is not None:
        belief_name = "P(Merlin)"
    else:
        belief_name = None
    return {
        "owner": memory.owner,
        "role": memory.private.role_name,
        "side": "Good" if memory.private.side else "Evil",
        "seenEvil": list(memory.private.seen_evil),
        "beliefName": belief_name,
        "cards": [
            {"quest": q, "passed": passed, "seq": result_seq.get(q)}
            for q, passed in sorted(memory.private.my_quest_cards.items())
        ],
        "log": [
            {"seq": e.seq, "kind": e.kind, "quest": e.quest, "attempt": e.attempt,
             "speaker": e.speaker, "text": e.text, "render": e.render()}
            for e in memory.log
        ],
        "teams": teams,
        "edges": talk,
        "flags": flags,
        "snaps": snaps,
    }


def build_data(events: Sequence[Dict[str, Any]], talk_edges: Sequence[Dict[str, Any]], title: str) -> Dict[str, Any]:
    steps: List[int] = []
    snaps: Dict[int, List[Dict[str, Any]]] = {}

    def on_step(seq: int, memories: Dict[int, PlayerMemory]) -> None:
        steps.append(seq)
        for seat, memory in memories.items():
            snaps.setdefault(seat, []).append(_snapshot(memory))

    replay = replay_arena_game(events, talk_edges, on_step=on_step)
    return {
        "title": title,
        "roles": {str(p): ROLE_NAMES[r] for p, r in replay.roles.items()},
        "trueEvil": replay.true_evil,
        "violations": replay.violations,
        "goodWon": replay.good_won,
        "steps": steps,
        "players": {str(seat): _player_data(m, snaps[seat]) for seat, m in replay.memories.items()},
    }


def render_html(data: Dict[str, Any]) -> str:
    payload = json.dumps(data).replace("</", "<\\/")
    return HTML.replace("__TITLE__", data["title"]).replace("__DATA__", payload)


def main(argv: Sequence[str]) -> None:
    args = list(argv)
    out = None
    if "-o" in args:
        i = args.index("-o")
        out = args[i + 1]
        del args[i:i + 2]
    if not args:
        print(__doc__)
        return
    game_path = args[0]
    edges = load_talk_edges(args[1]) if len(args) > 1 else []
    out = out or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(game_path))), "memory_viz.html")
    title = os.path.basename(os.path.dirname(os.path.dirname(os.path.abspath(game_path))))
    html = render_html(build_data(load_events(game_path), edges, title))
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {out}")


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Player memory · __TITLE__</title>
<style>
  :root {
    --bg: #ffffff; --surface: #f6f7f9; --stroke: #dde1e6; --text: #1c1f24; --muted: #6b7280;
    --accent: #2f6fed; --evil: #d14343; --good: #2e9e5b; --warn: #c98a0b; --merlin: #7a5af5;
    --s0: #2f6fed; --s1: #d14343; --s2: #2e9e5b; --s3: #c98a0b; --s4: #7a5af5;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #15171b; --surface: #1d2026; --stroke: #30343c; --text: #e6e8eb; --muted: #9aa1ab;
      --accent: #6c9bff; --evil: #f06a6a; --good: #4cc27e; --warn: #e0a83a; --merlin: #a48bff;
      --s0: #6c9bff; --s1: #f06a6a; --s2: #4cc27e; --s3: #e0a83a; --s4: #a48bff;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text); font: 13px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
  .wrap { max-width: 1320px; margin: 0 auto; padding: 20px 24px 40px; }
  h1 { font-size: 20px; margin: 0 0 4px; font-weight: 600; }
  h2 { font-size: 13px; margin: 0 0 8px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }
  .sub { color: var(--muted); }
  .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .chip { border: 1px solid var(--stroke); border-radius: 999px; padding: 2px 10px; font-size: 12px; }
  .chip.evil { color: var(--evil); } .chip.good { color: var(--good); }
  .banner { margin-top: 10px; padding: 8px 12px; border-left: 3px solid var(--warn); background: var(--surface); }
  .tabs { display: flex; gap: 4px; margin: 18px 0 10px; }
  .tab { border: 1px solid var(--stroke); background: var(--bg); color: var(--text); padding: 7px 14px; border-radius: 6px; cursor: pointer; font: inherit; }
  .tab.on { border-color: var(--accent); color: var(--accent); font-weight: 600; }
  .tab small { color: var(--muted); font-weight: 400; margin-left: 4px; }
  .controls { display: flex; gap: 10px; align-items: center; padding: 10px 0 14px; border-bottom: 1px solid var(--stroke); }
  .controls input[type=range] { flex: 1; accent-color: var(--accent); }
  button.b { border: 1px solid var(--stroke); background: var(--surface); color: var(--text); border-radius: 6px; padding: 4px 10px; cursor: pointer; font: inherit; }
  button.b:hover { border-color: var(--accent); }
  .now { padding: 8px 0 0; min-height: 28px; }
  .now .seq { color: var(--muted); margin-right: 6px; font-variant-numeric: tabular-nums; }
  .grid { display: grid; grid-template-columns: 560px 1fr; gap: 24px; margin-top: 16px; }
  .panel { background: var(--surface); border: 1px solid var(--stroke); border-radius: 8px; padding: 14px; }
  .open { padding: 2px 0; }
  svg text { fill: var(--text); font-family: inherit; }
  .edge { cursor: pointer; fill: none; }
  .edge.dim { opacity: .18; }
  .node { cursor: default; }
  .legend { display: flex; gap: 14px; flex-wrap: wrap; color: var(--muted); font-size: 12px; margin-top: 6px; }
  .sw { display: inline-block; width: 18px; height: 0; border-top: 2px solid; vertical-align: middle; margin-right: 5px; }
  .sw.dash { border-top-style: dashed; }
  .constraints div { font-family: ui-monospace, Consolas, monospace; font-size: 12px; padding: 2px 0; }
  .warn { color: var(--warn); }
  table { border-collapse: collapse; width: 100%; }
  td, th { text-align: left; padding: 5px 8px; border-bottom: 1px solid var(--stroke); white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; font-size: 12px; }
  tr.team { cursor: pointer; } tr.team:hover td { background: var(--surface); }
  tr.team.sel td { background: var(--surface); }
  tr.team.sel td:first-child { border-left: 3px solid var(--accent); }
  .v { display: inline-block; width: 20px; text-align: center; border-radius: 3px; font-size: 11px; margin-right: 2px; }
  .v.y { color: var(--good); border: 1px solid var(--good); } .v.n { color: var(--muted); border: 1px solid var(--stroke); }
  .res.fail { color: var(--evil); font-weight: 600; } .res.pass { color: var(--good); font-weight: 600; }
  .log { max-height: 420px; overflow-y: auto; font-size: 12.5px; position: relative; }
  .log div { padding: 4px 6px; border-radius: 4px; }
  .log .sys { color: var(--muted); }
  .log .private { color: var(--merlin); }
  .log .hl { background: color-mix(in srgb, var(--accent) 16%, transparent); }
  .log .spk { font-weight: 600; margin-right: 4px; }
  .detail .q { padding: 6px 0; border-bottom: 1px solid var(--stroke); }
  .detail .q:last-child { border-bottom: 0; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-top: 24px; }
  label.tg { color: var(--muted); display: flex; align-items: center; gap: 6px; cursor: pointer; }
</style>
</head>
<body>
<div class="wrap">
  <div id="header"></div>
  <div class="tabs" id="tabs"></div>
  <div class="controls">
    <button class="b" id="prev">Prev</button>
    <button class="b" id="play">Play</button>
    <button class="b" id="next">Next</button>
    <input type="range" id="slider" min="0" value="0">
    <span id="jumps" class="row"></span>
    <label class="tg"><input type="checkbox" id="truth"> Show true roles</label>
  </div>
  <div class="now" id="now"></div>
  <div class="grid">
    <div>
      <h2 id="graphTitle">Knowledge graph</h2>
      <svg id="graph" width="560" height="500" viewBox="0 0 560 500"></svg>
      <div class="legend">
        <span><span class="sw" style="border-color:var(--evil)"></span>accused</span>
        <span><span class="sw dash" style="border-color:var(--good)"></span>defended</span>
        <span><span style="color:var(--warn);font-weight:700">!</span> said one thing, voted another</span>
        <span>Line width = times said. Click a line for quotes.</span>
      </div>
    </div>
    <div style="display:flex;flex-direction:column;gap:18px">
      <div class="panel" id="beliefPanel"></div>
      <div class="open"><h2>Constraints this player derived</h2><div class="constraints" id="constraints"></div></div>
      <div class="panel detail" id="detail"></div>
    </div>
  </div>
  <div class="two">
    <div><h2>Teams (click to show votes on the graph)</h2><div id="teams"></div></div>
    <div><h2>What this player heard</h2><div class="log panel" id="log"></div></div>
  </div>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const N = Object.keys(D.roles).length;
const S = { seat: Object.values(D.players).find(p => p.role === 'Loyal Servant')?.owner ?? 0,
            i: D.steps.length - 1, truth: false, edgeKey: null, team: null, timer: null };
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const P = () => D.players[S.seat];
const seqNow = () => D.steps[S.i];
const snap = () => P().snaps[S.i];
const roleShort = r => ({'Loyal Servant':'Servant'}[r] || r);

function header() {
  const roles = Object.entries(D.roles).map(([p, r]) =>
    `<span class="chip ${D.trueEvil.includes(+p) ? 'evil' : 'good'}">P${p} ${esc(r)}</span>`).join('');
  const outcome = D.goodWon === null ? 'unfinished' : (D.goodWon ? 'Good won' : 'Evil won');
  const viol = D.violations.length
    ? `<div class="banner"><b>Rule violations in the recorded game:</b> ${D.violations.map(esc).join('; ')}</div>` : '';
  $('header').innerHTML = `<h1>Player memory replay</h1>
    <div class="sub">${esc(D.title)} · ${outcome} · ${D.steps.length} steps. Each tab is one player's own memory: only what they heard and saw.</div>
    <div class="row" style="margin-top:10px">${roles}</div>${viol}`;
  const quests = Object.values(D.players)[0].log.filter(e => e.kind === 'quest_result');
  $('jumps').innerHTML = quests.map(e => `<button class="b" data-seq="${e.seq}">Q${e.quest}</button>`).join('');
  $('jumps').querySelectorAll('button').forEach(b => b.onclick = () => go(D.steps.indexOf(+b.dataset.seq)));
}

function tabs() {
  $('tabs').innerHTML = Object.values(D.players).map(p =>
    `<button class="tab ${p.owner === S.seat ? 'on' : ''}" data-s="${p.owner}">Player ${p.owner}<small>${esc(roleShort(p.role))}</small></button>`).join('');
  $('tabs').querySelectorAll('button').forEach(b => b.onclick = () => { S.seat = +b.dataset.s; S.edgeKey = null; render(); });
}

function nowLine() {
  const e = P().log.find(x => x.seq === seqNow());
  $('now').innerHTML = e ? `<span class="seq">step ${S.i + 1}/${D.steps.length}</span>${esc(e.render)}` : '';
}

const RING = 165;
function pos(p, r = RING) {
  const a = -Math.PI / 2 + 2 * Math.PI * p / N;
  return [280 + r * Math.cos(a), 250 + r * Math.sin(a)];
}

function visibleEdges() {
  const n = snap().edgeCount;
  return P().edges.filter(e => e.id < n);
}
function visibleFlags() {
  const n = snap().edgeCount;
  return P().flags.filter(f => f.vote < n);
}
function groups() {
  const g = {};
  for (const e of visibleEdges()) {
    if (e.type !== 'accused' && e.type !== 'defended') continue;
    const k = `${e.type}:${e.src}:${e.dst}`;
    (g[k] ||= { key: k, type: e.type, src: e.src, dst: e.dst, edges: [] }).edges.push(e);
  }
  return Object.values(g);
}

function nodeInfo(p) {
  const me = P(), s = snap();
  if (p === me.owner) return { label: 'you', fill: 'var(--bg)', strong: true };
  if (me.seenEvil.includes(p)) return { label: me.side === 'Evil' ? 'evil ally' : 'known evil', fill: 'color-mix(in srgb, var(--evil) 70%, var(--bg))' };
  if (me.role === 'Merlin') return { label: 'known good', fill: 'var(--surface)' };
  const b = s.beliefs[p];
  if (b === undefined) return { label: '', fill: 'var(--surface)' };
  const color = me.beliefName === 'P(Merlin)' ? 'var(--merlin)' : 'var(--evil)';
  return { label: `${me.beliefName} ${b.toFixed(2)}`, fill: `color-mix(in srgb, ${color} ${Math.round(b * 85)}%, var(--bg))` };
}

function graph() {
  const svg = $('graph'), me = P();
  const team = S.team && me.teams.find(t => t.label === S.team && t.proposedSeq <= seqNow());
  const flags = visibleFlags();
  const flagged = new Set(flags.map(f => f.talk));
  let h = `<defs>
    <marker id="ma" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="11" markerHeight="11" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" style="fill:var(--evil)"/></marker>
    <marker id="md" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="11" markerHeight="11" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" style="fill:var(--good)"/></marker>
  </defs>`;
  for (const g of groups()) {
    const [x1, y1] = pos(g.src), [x2, y2] = pos(g.dst);
    const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy), ux = dx / len, uy = dy / len;
    const bend = g.type === 'accused' ? 0.16 : 0.32;
    const mx = (x1 + x2) / 2 - uy * len * bend, my = (y1 + y2) / 2 + ux * len * bend;
    const sx = x1 + ux * 36, sy = y1 + uy * 36, ex = x2 - ux * 40, ey = y2 - uy * 40;
    const acc = g.type === 'accused';
    const dim = S.edgeKey && S.edgeKey !== g.key ? ' dim' : '';
    const w = 1.4 + 1.1 * Math.min(g.edges.length, 5);
    h += `<path class="edge${dim}" data-k="${g.key}" d="M${sx},${sy} Q${mx},${my} ${ex},${ey}"
      style="stroke:var(${acc ? '--evil' : '--good'});stroke-width:${w}${acc ? '' : ';stroke-dasharray:6 4'}"
      marker-end="url(#${acc ? 'ma' : 'md'})"/>`;
    h += `<path class="edge" data-k="${g.key}" d="M${sx},${sy} Q${mx},${my} ${ex},${ey}" style="stroke:transparent;stroke-width:14"/>`;
    if (g.edges.some(e => flagged.has(e.id))) {
      const fx = 0.25 * sx + 0.5 * mx + 0.25 * ex, fy = 0.25 * sy + 0.5 * my + 0.25 * ey;
      h += `<circle cx="${fx}" cy="${fy}" r="8" style="fill:var(--bg);stroke:var(--warn);stroke-width:1.5"/>
        <text x="${fx}" y="${fy + 4}" text-anchor="middle" style="fill:var(--warn);font-weight:700;font-size:12px;pointer-events:none">!</text>`;
    }
  }
  for (let p = 0; p < N; p++) {
    const [x, y] = pos(p), info = nodeInfo(p);
    const onTeam = team && team.members.includes(p);
    const ring = onTeam ? 'stroke:var(--accent);stroke-width:3.5' : `stroke:var(--stroke);stroke-width:${info.strong ? 3 : 1.5}`;
    h += `<g class="node"><circle cx="${x}" cy="${y}" r="32" style="fill:${info.fill};${ring}"/>
      <text x="${x}" y="${y + 5}" text-anchor="middle" style="font-weight:600;font-size:15px">P${p}</text>`;
    const [lx, ly] = pos(p, RING + 52);
    h += `<text x="${lx}" y="${ly}" text-anchor="middle" style="font-size:12px">${esc(info.label)}</text>`;
    if (S.truth) h += `<text x="${lx}" y="${ly + 15}" text-anchor="middle" style="font-size:11px;fill:${D.trueEvil.includes(p) ? 'var(--evil)' : 'var(--muted)'}">${esc(roleShort(D.roles[p]))}</text>`;
    if (team && team.voteSeq !== null && team.voteSeq <= seqNow()) {
      const yes = team.votes[p];
      const [vx, vy] = pos(p, RING - 50);
      h += `<text x="${vx}" y="${vy + 4}" text-anchor="middle" style="font-size:11px;font-weight:600;fill:${yes ? 'var(--good)' : 'var(--muted)'}">${yes ? 'approve' : 'reject'}${team.leader === p ? ' · leader' : ''}</text>`;
    } else if (team && team.leader === p) {
      const [vx, vy] = pos(p, RING - 50);
      h += `<text x="${vx}" y="${vy + 4}" text-anchor="middle" style="font-size:11px;fill:var(--muted)">leader</text>`;
    }
    h += `</g>`;
  }
  if (team) {
    const res = team.resultSeq !== null && team.resultSeq <= seqNow()
      ? (team.success ? 'quest passed' : `quest failed, ${team.fails} fail(s)`)
      : team.voteSeq !== null && team.voteSeq <= seqNow() ? (team.approved ? 'approved' : 'rejected') : 'proposed';
    h += `<text x="280" y="255" text-anchor="middle" style="font-size:13px;font-weight:600">${team.label} {${team.members.join(',')}}</text>
      <text x="280" y="273" text-anchor="middle" style="font-size:12px;fill:var(--muted)">${res}</text>`;
  }
  svg.innerHTML = h;
  svg.querySelectorAll('path.edge').forEach(el => el.onclick = () => {
    S.edgeKey = S.edgeKey === el.dataset.k ? null : el.dataset.k; render();
  });
  $('graphTitle').textContent = `Knowledge graph of Player ${me.owner} (${me.role})`;
}

function beliefChart() {
  const me = P();
  if (!me.beliefName) {
    const known = me.seenEvil.map(p => 'P' + p).join(', ');
    $('beliefPanel').innerHTML = `<h2>Private knowledge</h2><div>Merlin sees the evil players from the start: <b>${known}</b>. Merlin keeps no belief scores; the challenge is to act on this without being identified.</div>${cards()}`;
    return;
  }
  const W = 640, H = 230, L = 44, R = 12, T = 12, B = 40;
  const xs = D.steps, x0 = xs[0], x1 = xs[xs.length - 1];
  const X = s => L + (W - L - R) * (s - x0) / (x1 - x0), Y = v => T + (H - T - B) * (1 - v);
  const players = Object.keys(me.snaps[0].beliefs).map(Number);
  let h = '';
  for (const v of [0, 0.5, 1]) h += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" style="stroke:var(--stroke)"/><text x="${L - 6}" y="${Y(v) + 4}" text-anchor="end" style="font-size:11px;fill:var(--muted)">${v}</text>`;
  for (const e of me.log.filter(e => e.kind === 'quest_result')) {
    const fail = !Object.values(D.players)[0].teams.find(t => t.resultSeq === e.seq)?.success;
    h += `<line x1="${X(e.seq)}" x2="${X(e.seq)}" y1="${T}" y2="${H - B}" style="stroke:var(${fail ? '--evil' : '--good'});stroke-dasharray:2 3;opacity:.7"/>
      <text x="${X(e.seq)}" y="${H - B + 14}" text-anchor="middle" style="font-size:10px;fill:var(--muted)">Q${e.quest} ${fail ? 'fail' : 'pass'}</text>`;
  }
  for (const p of players) {
    const pts = me.snaps.map((s, i) => `${X(xs[i])},${Y(s.beliefs[p])}`).join(' ');
    h += `<polyline points="${pts}" style="fill:none;stroke:var(--s${p});stroke-width:2"/>`;
  }
  h += `<line x1="${X(seqNow())}" x2="${X(seqNow())}" y1="${T}" y2="${H - B}" style="stroke:var(--text);stroke-width:1"/>`;
  h += `<text x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle" style="font-size:11px;fill:var(--muted)">Transcript seq (game time)</text>
    <text x="12" y="${(T + H - B) / 2}" text-anchor="middle" transform="rotate(-90 12 ${(T + H - B) / 2})" style="font-size:11px;fill:var(--muted)">${me.beliefName}</text>`;
  const legend = players.map(p => `<span><span class="sw" style="border-color:var(--s${p})"></span>P${p} ${snap().beliefs[p].toFixed(2)}</span>`).join('');
  const what = me.beliefName === 'P(evil)'
    ? 'Rule-based P(evil) from votes and failed quests. Sums to 2 across opponents.'
    : 'P(Merlin) from vote accuracy and early accusations of evil. Sums to 1 across good players.';
  $('beliefPanel').innerHTML = `<h2>${me.beliefName} of Player ${me.owner} over the game</h2>
    <svg width="100%" viewBox="0 0 ${W} ${H}">${h}</svg>
    <div class="legend">${legend}</div><div class="sub" style="margin-top:6px">${what} Source: replay of ${esc(D.title)}.</div>${cards()}`;
}

function cards() {
  const c = P().cards.filter(c => c.seq !== null && c.seq <= seqNow());
  if (!c.length) return '';
  return `<div style="margin-top:8px" class="sub">Quest cards only this player knows: ${c.map(c => `Q${c.quest} <b style="color:var(${c.passed ? '--good' : '--evil'})">${c.passed ? 'Pass' : 'Fail'}</b>`).join(', ')}</div>`;
}

function constraints() {
  const s = snap();
  const lines = s.constraints.map(l => `<div>${esc(l.replace('Constraints: ', ''))}</div>`).join('');
  const warn = s.consistent ? '' : `<div class="warn" style="font-family:inherit;margin-top:6px">No evil pair explains every failed quest. Beliefs use the pairs that explain the most.</div>`;
  $('constraints').innerHTML = (lines || '<div class="sub" style="font-family:inherit">No failed quests yet, so nothing is ruled out.</div>') + warn;
}

function detail() {
  const g = S.edgeKey && groups().find(g => g.key === S.edgeKey);
  if (!g) {
    const flags = visibleFlags();
    const list = flags.map(f => {
      const t = P().edges.find(e => e.id === f.talk);
      return `<div class="q"><b>P${t.src}</b> accused P${t.dst} (#${t.seq}) then approved ${f.team} (#${f.voteSeq})</div>`;
    }).join('');
    $('detail').innerHTML = `<h2>Contradictions so far (${flags.length})</h2>${list || '<div class="sub">None yet.</div>'}<div class="sub" style="margin-top:8px">Click a line on the graph to see the quotes behind it.</div>`;
    return;
  }
  const flags = visibleFlags();
  const qs = g.edges.map(e => {
    const f = flags.filter(f => f.talk === e.id).map(f => `<div class="warn">then approved ${f.team} (#${f.voteSeq})</div>`).join('');
    return `<div class="q"><span class="sub">#${e.sources.join(', #')} · Q${P().log.find(x => x.seq === e.seq)?.quest}</span><br>"${esc(e.quote)}"${f}</div>`;
  }).join('');
  $('detail').innerHTML = `<h2>P${g.src} ${g.type} P${g.dst} (${g.edges.length}×)</h2>${qs}`;
}

function teamsTable() {
  const me = P(), t = seqNow();
  const rows = me.teams.filter(x => x.proposedSeq <= t).map(x => {
    const voted = x.voteSeq !== null && x.voteSeq <= t;
    const votes = voted ? [...Array(N).keys()].map(p => `<span class="v ${x.votes[p] ? 'y' : 'n'}" title="P${p}">${p}</span>`).join('') : '<span class="sub">voting</span>';
    let res = '';
    if (x.resultSeq !== null && x.resultSeq <= t) res = x.success ? '<span class="res pass">PASS</span>' : `<span class="res fail">FAIL ×${x.fails}</span>`;
    else if (voted) res = x.approved ? 'approved' : '<span class="sub">rejected</span>';
    return `<tr class="team ${S.team === x.label ? 'sel' : ''}" data-l="${x.label}"><td><b>${x.label}</b></td><td>P${x.leader}</td><td>{${x.members.join(', ')}}</td><td>${votes}</td><td>${res}</td></tr>`;
  }).reverse().join('');
  $('teams').innerHTML = `<table><tr><th>Team</th><th>Leader</th><th>Members</th><th>Approved by (filled)</th><th>Result</th></tr>${rows}</table>`;
  $('teams').querySelectorAll('tr.team').forEach(r => r.onclick = () => { S.team = S.team === r.dataset.l ? null : r.dataset.l; render(); });
}

function log() {
  const me = P(), t = seqNow();
  const g = S.edgeKey && groups().find(g => g.key === S.edgeKey);
  const hl = new Set(g ? g.edges.flatMap(e => e.sources) : []);
  const cardAt = Object.fromEntries(me.cards.filter(c => c.seq !== null).map(c => [c.seq, c]));
  let h = '';
  for (const e of me.log) {
    if (e.seq > t) break;
    if (cardAt[e.seq]) h += `<div class="private">Only you know: you played ${cardAt[e.seq].passed ? 'Pass' : 'Fail'} on Q${e.quest}</div>`;
    if (e.kind === 'utterance' || e.kind === 'evil_chat') {
      h += `<div class="${hl.has(e.seq) ? 'hl' : ''}" data-seq="${e.seq}"><span class="sub">#${e.seq}</span> <span class="spk">P${e.speaker}${e.speaker === me.owner ? ' (you)' : ''}</span>${esc(e.text)}</div>`;
    } else {
      h += `<div class="sys">${esc(e.render)}</div>`;
    }
  }
  const box = $('log');
  box.innerHTML = h;
  const first = box.querySelector('.hl');
  box.scrollTop = first ? first.offsetTop - 40 : box.scrollHeight;
}

function render() {
  $('slider').value = S.i;
  tabs(); nowLine(); graph(); beliefChart(); constraints(); detail(); teamsTable(); log();
}
function go(i) { S.i = Math.max(0, Math.min(D.steps.length - 1, i)); render(); }

$('slider').max = D.steps.length - 1;
$('slider').oninput = e => go(+e.target.value);
$('prev').onclick = () => go(S.i - 1);
$('next').onclick = () => go(S.i + 1);
$('truth').onchange = e => { S.truth = e.target.checked; render(); };
$('play').onclick = () => {
  if (S.timer) { clearInterval(S.timer); S.timer = null; $('play').textContent = 'Play'; return; }
  if (S.i >= D.steps.length - 1) S.i = 0;
  $('play').textContent = 'Pause';
  S.timer = setInterval(() => { if (S.i >= D.steps.length - 1) $('play').click(); else go(S.i + 1); }, 350);
};
document.addEventListener('keydown', e => {
  if (e.key === 'ArrowLeft') go(S.i - 1);
  if (e.key === 'ArrowRight') go(S.i + 1);
});
const hash = new URLSearchParams(location.hash.slice(1));
if (hash.has('seat') && D.players[hash.get('seat')]) S.seat = +hash.get('seat');
if (hash.has('seq')) S.i = Math.max(0, D.steps.findLastIndex(s => s <= +hash.get('seq')));
if (hash.has('team')) S.team = hash.get('team');
if (hash.has('edge')) S.edgeKey = hash.get('edge');
S.truth = hash.get('truth') === '1';
$('truth').checked = S.truth;
header();
render();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main(sys.argv[1:])
