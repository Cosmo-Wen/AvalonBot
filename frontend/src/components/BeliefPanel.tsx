import { useEffect, useMemo, useState } from "react";
import { type BeliefSnapshot, type PlayerMemoryView, type QuestResult, SEAT_COLORS, seatName } from "../types";

interface BeliefPanelProps {
  memory: Record<number, PlayerMemoryView>;
  history: Record<number, BeliefSnapshot[]>;
  quests: (QuestResult | null)[];
}

const W = 260;
const H = 130;
const PAD = { top: 8, right: 34, bottom: 18, left: 26 };

export function BeliefPanel({ memory, history, quests }: BeliefPanelProps) {
  const holders = useMemo(
    () => Object.values(memory).filter((m) => m.beliefName).map((m) => m.owner).sort(),
    [memory]
  );
  const [seat, setSeat] = useState<number | null>(null);
  useEffect(() => {
    if (seat === null || !holders.includes(seat)) {
      const servant = holders.find((s) => memory[s]?.beliefName === "P(evil)");
      setSeat(servant ?? holders[0] ?? null);
    }
  }, [holders, seat, memory]);

  const view = seat !== null ? memory[seat] : undefined;
  const snaps = seat !== null ? history[seat] ?? [] : [];

  const chart = useMemo(() => {
    if (snaps.length === 0) return null;
    const first = snaps[0].seq;
    const last = Math.max(snaps[snaps.length - 1].seq, ...quests.filter(Boolean).map((q) => q!.seq));
    const span = Math.max(1, last - first);
    const x = (s: number) => PAD.left + ((s - first) / span) * (W - PAD.left - PAD.right);
    const y = (v: number) => PAD.top + (1 - v) * (H - PAD.top - PAD.bottom);
    const targets = Object.keys(snaps[snaps.length - 1].values).map(Number);
    const lines = targets.map((t) => {
      let d = "";
      snaps.forEach((s, i) => {
        const v = s.values[t] ?? 0;
        if (i === 0) d += `M${x(s.seq)},${y(v)}`;
        else d += ` H${x(s.seq)} V${y(v)}`;
      });
      d += ` H${x(last)}`;
      return { t, d, end: snaps[snaps.length - 1].values[t] ?? 0 };
    });
    return { x, y, lines, last };
  }, [snaps, quests]);

  return (
    <div className="rounded-2xl border border-medieval-border bg-medieval-darker p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="font-display text-[11px] uppercase tracking-[0.18em] text-medieval-gold-dim">
          {view?.beliefName ?? "Beliefs"} over time
        </h3>
        {holders.length > 0 && (
          <select
            value={seat ?? ""}
            onChange={(e) => setSeat(Number(e.target.value))}
            className="rounded-full border border-medieval-border bg-medieval-dark px-2 py-0.5 font-body text-[11px] text-medieval-parchment-dim focus:outline-none"
          >
            {holders.map((s) => (
              <option key={s} value={s}>
                {seatName(s)} ({memory[s].role})
              </option>
            ))}
          </select>
        )}
      </div>

      {!chart || !view ? (
        <p className="py-6 text-center font-body text-xs text-medieval-silver">
          Beliefs appear once the game starts. Servants track P(evil); evil players track P(Merlin).
        </p>
      ) : (
        <>
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`${view.beliefName} held by ${seatName(view.owner)} over the game`}>
            {[0, 0.5, 1].map((v) => (
              <g key={v}>
                <line x1={PAD.left} x2={W - PAD.right} y1={chart.y(v)} y2={chart.y(v)} stroke="#2a2a3a" strokeWidth="0.6" />
                <text x={PAD.left - 4} y={chart.y(v) + 3} textAnchor="end" fontSize="8" fill="#9a9aaa">{v}</text>
              </g>
            ))}
            {quests.filter((q): q is QuestResult => q !== null).map((q) => (
              <g key={q.quest}>
                <line x1={chart.x(q.seq)} x2={chart.x(q.seq)} y1={PAD.top} y2={H - PAD.bottom} stroke={q.success ? "#4cc27e" : "#f06a6a"} strokeDasharray="2 2" strokeWidth="0.8" opacity="0.7" />
                <text x={chart.x(q.seq)} y={H - 6} textAnchor="middle" fontSize="7.5" fill="#9a9aaa">Q{q.quest}</text>
              </g>
            ))}
            {chart.lines.map((l) => (
              <g key={l.t}>
                <path d={l.d} fill="none" stroke={SEAT_COLORS[l.t]} strokeWidth="1.6" strokeLinejoin="round" />
                <text x={W - PAD.right + 3} y={chart.y(l.end) + 3} fontSize="8" fill={SEAT_COLORS[l.t]} fontFamily="JetBrains Mono, monospace">
                  {l.end.toFixed(2)}
                </text>
              </g>
            ))}
          </svg>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
            {chart.lines.map((l) => (
              <span key={l.t} className="flex items-center gap-1 font-body text-[11px] text-medieval-parchment-dim">
                <span className="inline-block h-0.5 w-3 rounded" style={{ background: SEAT_COLORS[l.t] }} />
                {seatName(l.t)}
              </span>
            ))}
          </div>
          <p className="mt-1.5 font-body text-[10px] text-medieval-silver/70">
            x: game time (event number) · dashed lines: quest results
          </p>
        </>
      )}
    </div>
  );
}
