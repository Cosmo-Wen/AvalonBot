import { useMemo, useState } from "react";
import { type MemoryEdge, type Player, type PlayerMemoryView, ROLE_DISPLAY, SEAT_COLORS, seatName } from "../types";

interface KnowledgeGraphViewProps {
  memory: Record<number, PlayerMemoryView>;
  players: Player[];
  showRoles: boolean;
}

interface EdgeGroup {
  key: string;
  type: "accused" | "defended";
  src: number;
  dst: number;
  edges: MemoryEdge[];
  flagged: boolean;
}

const RED = "#f06a6a";
const GREEN = "#4cc27e";
const WARN = "#e0a83a";
const PURPLE = "#a48bff";

function groupEdges(view: PlayerMemoryView): EdgeGroup[] {
  const flagged = new Set(view.flags.map((f) => f.talk));
  const groups = new Map<string, EdgeGroup>();
  for (const e of view.edges) {
    if (e.type !== "accused" && e.type !== "defended") continue;
    const key = `${e.type}:${e.src}:${e.dst}`;
    const g = groups.get(key) ?? { key, type: e.type, src: e.src, dst: e.dst as number, edges: [], flagged: false };
    g.edges.push(e);
    g.flagged ||= flagged.has(e.id);
    groups.set(key, g);
  }
  return [...groups.values()];
}

function nodeState(view: PlayerMemoryView, seat: number): { fill: string; label: string } {
  if (seat === view.owner) return { fill: "#14141e", label: "self" };
  if (view.seenEvil.includes(seat)) {
    return { fill: "rgba(196,43,43,0.75)", label: view.side === "Evil" ? "ally" : "known evil" };
  }
  if (view.role === "Merlin") return { fill: "rgba(46,158,91,0.35)", label: "known good" };
  const b = view.beliefs[String(seat)];
  if (b === undefined) return { fill: "#1c1c28", label: "" };
  const color = view.beliefName === "P(Merlin)" ? "164,139,255" : "240,106,106";
  return { fill: `rgba(${color},${0.08 + b * 0.8})`, label: b.toFixed(2) };
}

export function MemoryGraph({
  view,
  players,
  showRoles,
  compact = false,
  selected,
  onSelect,
}: {
  view: PlayerMemoryView;
  players: Player[];
  showRoles: boolean;
  compact?: boolean;
  selected?: string | null;
  onSelect?: (key: string | null) => void;
}) {
  const groups = useMemo(() => groupEdges(view), [view]);
  const C = 200;
  const R = compact ? 128 : 136;
  const NR = compact ? 24 : 27;
  const pos = (p: number, r = R): [number, number] => {
    const a = -Math.PI / 2 + (2 * Math.PI * p) / 5;
    return [C + r * Math.cos(a), C + r * Math.sin(a)];
  };
  const claims = view.edges.filter((e) => e.type === "claimed_role");

  return (
    <svg viewBox="0 0 400 400" className="h-auto w-full">
      <defs>
        {[["acc", RED], ["def", GREEN]].map(([id, color]) => (
          <marker key={id} id={`${id}-${view.owner}-${compact}`} viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="10" markerHeight="10" orient="auto">
            <path d="M0,0L10,5L0,10z" fill={color} />
          </marker>
        ))}
      </defs>

      {groups.map((g) => {
        const [x1, y1] = pos(g.src);
        const [x2, y2] = pos(g.dst);
        const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy), ux = dx / len, uy = dy / len;
        const bend = g.type === "accused" ? 0.14 : 0.3;
        const mx = (x1 + x2) / 2 - uy * len * bend, my = (y1 + y2) / 2 + ux * len * bend;
        const sx = x1 + ux * (NR + 3), sy = y1 + uy * (NR + 3), ex = x2 - ux * (NR + 6), ey = y2 - uy * (NR + 6);
        const d = `M${sx},${sy} Q${mx},${my} ${ex},${ey}`;
        const acc = g.type === "accused";
        const dim = selected && selected !== g.key;
        const fx = 0.25 * sx + 0.5 * mx + 0.25 * ex, fy = 0.25 * sy + 0.5 * my + 0.25 * ey;
        return (
          <g key={`${g.key}:${g.edges.length}`} className="edge-in" style={{ opacity: dim ? 0.15 : 1, cursor: onSelect ? "pointer" : "default" }} onClick={() => onSelect?.(selected === g.key ? null : g.key)}>
            <path d={d} fill="none" stroke="transparent" strokeWidth={14} />
            <path
              d={d}
              fill="none"
              stroke={acc ? RED : GREEN}
              strokeOpacity={0.85}
              strokeWidth={1.2 + Math.min(g.edges.length, 5) * 0.9}
              strokeDasharray={acc ? undefined : "6 4"}
              markerEnd={`url(#${acc ? "acc" : "def"}-${view.owner}-${compact})`}
            />
            {g.flagged && (
              <g>
                <circle cx={fx} cy={fy} r={7.5} fill="#0a0a0f" stroke={WARN} strokeWidth={1.5} />
                <text x={fx} y={fy + 3.8} textAnchor="middle" fontSize="11" fontWeight="700" fill={WARN}>!</text>
              </g>
            )}
          </g>
        );
      })}

      {[0, 1, 2, 3, 4].map((p) => {
        const [x, y] = pos(p);
        const st = nodeState(view, p);
        const isOwner = p === view.owner;
        const [lx, ly] = pos(p, R + NR + 15);
        const player = players[p];
        const claim = claims.filter((c) => c.src === p).pop();
        return (
          <g key={p}>
            <circle cx={x} cy={y} r={NR} fill={st.fill} stroke={isOwner ? "#c9a84c" : SEAT_COLORS[p]} strokeOpacity={isOwner ? 1 : 0.5} strokeWidth={isOwner ? 3 : 1.5} style={{ transition: "fill 700ms" }} />
            <text x={x} y={y + 1} textAnchor="middle" fontSize={compact ? 12 : 13} fontWeight="700" fill="#e8dcc8" fontFamily="Cinzel, serif">
              {seatName(p).slice(0, 3)}
            </text>
            <text x={x} y={y + 13} textAnchor="middle" fontSize="9" fill="#e8dcc8" fillOpacity={0.85} fontFamily="JetBrains Mono, monospace">
              {st.label}
            </text>
            {showRoles && player?.role && !isOwner && (
              <text x={lx} y={ly + 4} textAnchor="middle" fontSize="10" fill={player.side === "evil" ? RED : player.role === "merlin" ? PURPLE : "#9a9aaa"}>
                {ROLE_DISPLAY[player.role]}
              </text>
            )}
            {claim && (
              <text x={lx} y={ly + (showRoles ? 16 : 4)} textAnchor="middle" fontSize="9" fill={WARN}>
                claims {claim.role}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

function BeliefBars({ view }: { view: PlayerMemoryView }) {
  if (!view.beliefName) {
    return (
      <p className="font-body text-xs text-medieval-parchment-dim">
        Merlin knows the evil players from the start ({view.seenEvil.map((s) => seatName(s)).join(", ")}) and keeps no belief scores.
      </p>
    );
  }
  const entries = Object.entries(view.beliefs).map(([p, v]) => [Number(p), v] as const).sort((a, b) => b[1] - a[1]);
  const color = view.beliefName === "P(Merlin)" ? PURPLE : RED;
  return (
    <div className="flex flex-col gap-1.5">
      {entries.map(([p, v]) => (
        <div key={p} className="flex items-center gap-2 text-xs">
          <span className="w-16 font-display" style={{ color: SEAT_COLORS[p] }}>{seatName(p)}</span>
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-medieval-border/50">
            <div className="h-full rounded-full transition-all duration-700 ease-fluid" style={{ width: `${v * 100}%`, background: color }} />
          </div>
          <span className="w-9 text-right font-mono text-medieval-parchment">{v.toFixed(2)}</span>
        </div>
      ))}
      <p className="mt-1 font-body text-[11px] text-medieval-silver/70">
        {view.beliefName === "P(evil)"
          ? "Chance each player is evil, from votes and failed quests. Sums to 2."
          : "Chance each good player is Merlin, from vote accuracy and early accusations. Sums to 1."}
      </p>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-medieval-border bg-medieval-dark p-3.5">
      <h4 className="mb-2.5 font-display text-[10px] uppercase tracking-[0.2em] text-medieval-gold-dim">{title}</h4>
      {children}
    </div>
  );
}

function FocusPanel({ view, players, showRoles }: { view: PlayerMemoryView; players: Player[]; showRoles: boolean }) {
  const [selected, setSelected] = useState<string | null>(null);
  const groups = useMemo(() => groupEdges(view), [view]);
  const group = groups.find((g) => g.key === selected);
  const flagsById = new Map(view.flags.map((f) => [f.talk, f] as const));
  const teamTalk = view.edges.filter((e) => e.type === "backed_team" || e.type === "opposed_team");
  const cards = Object.entries(view.cards);

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
      <div className="flex flex-col gap-3">
        <div className="rounded-2xl border border-medieval-border bg-medieval-darker p-3">
          <MemoryGraph view={view} players={players} showRoles={showRoles} selected={selected} onSelect={setSelected} />
          <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 pb-1 font-body text-[11px] text-medieval-silver">
            <span><span className="mr-1 inline-block h-0.5 w-4 align-middle" style={{ background: RED }} />accused</span>
            <span><span className="mr-1 inline-block w-4 border-t-2 border-dashed align-middle" style={{ borderColor: GREEN }} />defended</span>
            <span><span className="font-bold" style={{ color: WARN }}>!</span> said one thing, voted another</span>
            <span>Thicker = said more often. Click a line for quotes.</span>
          </div>
        </div>
        <Section title={group ? `${seatName(group.src)} ${group.type} ${seatName(group.dst)} · ${group.edges.length}×` : "What was said"}>
          {group ? (
            <div className="flex max-h-64 flex-col gap-2 overflow-y-auto">
              {group.edges.map((e) => (
                <div key={e.id} className="border-l-2 border-medieval-border pl-2.5">
                  <div className="font-mono text-[10px] text-medieval-silver/70">Quest {e.quest} · #{e.sources.join(", #")}</div>
                  <div className="font-body text-xs italic text-medieval-parchment">“{e.quote}”</div>
                  {flagsById.get(e.id) && (
                    <div className="font-body text-[11px]" style={{ color: WARN }}>
                      then approved {flagsById.get(e.id)!.team} (#{flagsById.get(e.id)!.voteSeq})
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : view.flags.length ? (
            <div className="flex max-h-64 flex-col gap-1 overflow-y-auto font-body text-xs text-medieval-parchment-dim">
              {view.flags.map((f, i) => {
                const t = view.edges.find((e) => e.id === f.talk);
                return t ? (
                  <div key={i}>
                    <span style={{ color: SEAT_COLORS[t.src] }}>{seatName(t.src)}</span> accused {seatName(t.dst as number)} (#{t.seq}), then approved{" "}
                    <span className="text-medieval-parchment">{f.team}</span> with them on it
                  </div>
                ) : null;
              })}
            </div>
          ) : (
            <p className="font-body text-xs text-medieval-silver">
              {groups.length ? "Click a line on the graph to see the quotes behind it." : "No accusations or defenses heard yet."}
            </p>
          )}
        </Section>
      </div>

      <div className="flex flex-col gap-3">
        <Section title={view.beliefName ?? "Private knowledge"}>
          <BeliefBars view={view} />
        </Section>
        <Section title="Constraints from failed quests">
          {view.constraints.length ? (
            <div className="flex flex-col gap-1 font-mono text-[11px] text-medieval-parchment">
              {view.constraints.map((c) => <div key={c}>{c}</div>)}
            </div>
          ) : (
            <p className="font-body text-xs text-medieval-silver">No failed quests yet, so nothing is ruled out.</p>
          )}
          {!view.consistent && (
            <p className="mt-2 font-body text-[11px]" style={{ color: WARN }}>
              No evil pair explains every failed quest (a rule was broken). Beliefs use the pairs that explain the most.
            </p>
          )}
          {cards.length > 0 && (
            <p className="mt-2 font-body text-[11px] text-medieval-silver">
              Only this player knows their own cards:{" "}
              {cards.map(([q, passed]) => (
                <span key={q} className="mr-2 font-mono" style={{ color: passed ? GREEN : RED }}>Q{q} {passed ? "Pass" : "Fail"}</span>
              ))}
            </p>
          )}
        </Section>
        <Section title={`Teams seen (${view.teams.length})`}>
          <div className="max-h-72 overflow-y-auto">
            <table className="w-full font-body text-[11px]">
              <thead>
                <tr className="text-left text-medieval-silver/70">
                  <th className="pb-1 font-normal">Team</th>
                  <th className="pb-1 font-normal">Members</th>
                  <th className="pb-1 font-normal">Votes</th>
                  <th className="pb-1 font-normal">Result</th>
                </tr>
              </thead>
              <tbody>
                {[...view.teams].reverse().map((t) => (
                  <tr key={t.label} className="border-t border-medieval-border/60">
                    <td className="py-1 font-mono text-medieval-parchment">{t.label}</td>
                    <td className="py-1 text-medieval-parchment-dim">{t.members.map((m) => seatName(m).slice(0, 3)).join(", ")}</td>
                    <td className="py-1">
                      <div className="flex gap-0.5">
                        {[0, 1, 2, 3, 4].map((p) => {
                          const v = t.votes[String(p)];
                          return (
                            <span
                              key={p}
                              title={`${seatName(p)}: ${v === undefined ? "—" : v ? "approve" : "reject"}`}
                              className="flex h-4 w-4 items-center justify-center rounded text-[9px]"
                              style={{ border: `1px solid ${v ? GREEN : "#2a2a3a"}`, color: v ? GREEN : "#6b6b7a" }}
                            >
                              {p}
                            </span>
                          );
                        })}
                      </div>
                    </td>
                    <td className="py-1">
                      {t.success === true && <span style={{ color: GREEN }}>Pass</span>}
                      {t.success === false && <span style={{ color: RED }}>Fail ×{t.fails}</span>}
                      {t.success === null && (t.approved === null ? <span className="text-medieval-silver">voting</span> : t.approved ? <span className="text-medieval-parchment-dim">approved</span> : <span className="text-medieval-silver/60">rejected</span>)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {teamTalk.length > 0 && (
            <div className="mt-2 flex flex-col gap-0.5 font-body text-[11px] text-medieval-parchment-dim">
              {teamTalk.slice(-6).map((e) => (
                <div key={e.id}>
                  {seatName(e.src)} {e.type === "backed_team" ? "backed" : "opposed"} {String(e.dst)} (#{e.seq})
                </div>
              ))}
            </div>
          )}
        </Section>
      </div>
    </div>
  );
}

export default function KnowledgeGraphView({ memory, players, showRoles }: KnowledgeGraphViewProps) {
  const [focus, setFocus] = useState<number | null>(null);
  const seats = Object.keys(memory).map(Number).sort();

  if (!seats.length) {
    return (
      <div className="flex h-full min-h-[420px] items-center justify-center rounded-2xl border border-medieval-border bg-medieval-darker font-body text-sm text-medieval-silver">
        Start a game or a replay. Each player's knowledge graph builds up here as they hear the discussion.
      </div>
    );
  }

  const tab = (active: boolean) =>
    `rounded-full border px-3.5 py-1.5 font-body text-xs transition-all duration-300 ${
      active ? "border-medieval-gold/50 bg-medieval-gold/10 text-medieval-gold" : "border-medieval-border text-medieval-silver hover:text-medieval-parchment"
    }`;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <button className={tab(focus === null)} onClick={() => setFocus(null)}>All players</button>
        {seats.map((s) => (
          <button key={s} className={tab(focus === s)} onClick={() => setFocus(s)}>
            <span style={{ color: SEAT_COLORS[s] }}>{seatName(s)}</span>
            <span className="ml-1.5 text-medieval-silver/70">{memory[s].role}</span>
          </button>
        ))}
        <span className="ml-auto font-body text-[11px] text-medieval-silver/70">
          Each graph is one player's own memory: only what they heard, saw and worked out.
        </span>
      </div>

      {focus !== null && memory[focus] ? (
        <FocusPanel key={focus} view={memory[focus]} players={players} showRoles={showRoles} />
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 2xl:grid-cols-3">
          {seats.map((s) => {
            const view = memory[s];
            const top = Object.entries(view.beliefs).sort((a, b) => b[1] - a[1])[0];
            return (
              <button
                key={s}
                onClick={() => setFocus(s)}
                className="group flex flex-col rounded-2xl border border-medieval-border bg-medieval-darker p-3 text-left transition-all duration-300 hover:border-medieval-gold/40"
              >
                <div className="flex items-baseline justify-between">
                  <span className="font-display text-sm" style={{ color: SEAT_COLORS[s] }}>{seatName(s)}</span>
                  <span className="font-body text-[11px] text-medieval-silver">{view.role}</span>
                </div>
                <MemoryGraph view={view} players={players} showRoles={showRoles} compact />
                <div className="flex items-center justify-between font-body text-[11px] text-medieval-parchment-dim">
                  <span>
                    {view.beliefName && top
                      ? `Top ${view.beliefName === "P(evil)" ? "suspect" : "Merlin guess"}: ${seatName(Number(top[0]))} ${top[1].toFixed(2)}`
                      : view.role === "Merlin" ? "Knows who is evil" : ""}
                  </span>
                  <span className="font-mono text-medieval-silver/70">
                    {view.edges.length} talk · {view.flags.length} !
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
