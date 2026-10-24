import { useMemo } from "react";
import type { BeliefSnapshot, QuestResult } from "../types";
import { SEAT_COLORS } from "../types";

interface BeliefPanelProps {
  beliefs: Record<number, BeliefSnapshot[]>;
  quests: (QuestResult | null)[];
  viewingSeat?: number;
}

const W = 100;
const H = 52;
const PAD = { top: 4, right: 6, bottom: 8, left: 8 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

function buildSeries(
  beliefs: Record<number, BeliefSnapshot[]>,
  viewingSeat?: number
): {
  seqs: number[];
  linesByTarget: Map<number, { seq: number; value: number }[]>;
} {
  const sourceSeats =
    viewingSeat !== undefined
      ? [viewingSeat]
      : Object.keys(beliefs).map(Number);

  const allSnaps: BeliefSnapshot[] = [];
  for (const seat of sourceSeats) {
    const snapList = beliefs[seat];
    if (snapList) allSnaps.push(...snapList);
  }
  allSnaps.sort((a, b) => a.seq - b.seq);

  const seqSet = new Set<number>();
  const targetSet = new Set<number>();
  const dataMap = new Map<string, number>();

  for (const snap of allSnaps) {
    seqSet.add(snap.seq);
    for (const [t, v] of Object.entries(snap.pEvil)) {
      const target = Number(t);
      targetSet.add(target);
      dataMap.set(`${snap.seq}:${target}`, v);
    }
  }

  const seqs = Array.from(seqSet).sort((a, b) => a - b);
  const linesByTarget = new Map<number, { seq: number; value: number }[]>();

  for (const target of Array.from(targetSet).sort()) {
    const points: { seq: number; value: number }[] = [];
    for (const seq of seqs) {
      const v = dataMap.get(`${seq}:${target}`);
      if (v !== undefined) {
        points.push({ seq, value: v });
      }
    }
    if (points.length > 0) {
      linesByTarget.set(target, points);
    }
  }

  return { seqs, linesByTarget };
}

export function BeliefPanel({ beliefs, quests, viewingSeat }: BeliefPanelProps) {
  const { seqs, linesByTarget } = useMemo(
    () => buildSeries(beliefs, viewingSeat),
    [beliefs, viewingSeat]
  );

  const hasData = seqs.length > 0 && linesByTarget.size > 0;

  const questMarkers = useMemo(() => {
    const markers: { seq: number; quest: number; passed: boolean }[] = [];
    for (const ev of Object.values(beliefs).flat()) {
      if (ev.seq > 0) {
        const questIdx = quests.findIndex(
          (q) => q !== null && q.quest === Math.ceil(ev.seq / 100)
        );
        if (questIdx >= 0) continue;
      }
    }
    return quests
      .filter((q): q is QuestResult => q !== null)
      .map((q, _i) => {
        const closestSeq = seqs.length > 0
          ? seqs[Math.min(Math.floor((q.quest / 5) * seqs.length), seqs.length - 1)]
          : q.quest;
        return { seq: closestSeq, quest: q.quest, passed: q.success };
      });
  }, [quests, beliefs, seqs]);

  const xScale = (seq: number) => {
    if (seqs.length <= 1) return PAD.left + PLOT_W / 2;
    const min = seqs[0];
    const max = seqs[seqs.length - 1];
    if (max === min) return PAD.left + PLOT_W / 2;
    return PAD.left + ((seq - min) / (max - min)) * PLOT_W;
  };

  const yScale = (v: number) => PAD.top + (1 - v) * PLOT_H;

  const gridYs = [0, 0.25, 0.5, 0.75, 1.0];

  return (
    <div className="rounded-[1.25rem] border border-medieval-border bg-medieval-darker p-[3px]">
      <div className="rounded-[calc(1.25rem-3px)] bg-medieval-dark p-4">
        <h3 className="font-display text-xs uppercase tracking-[0.15em] text-medieval-gold-dim mb-3">
          Belief Graph — P(evil)
        </h3>

        {!hasData ? (
          <div className="flex items-center justify-center h-32 text-medieval-silver text-sm font-body">
            Beliefs will appear after the first quest
          </div>
        ) : (
          <>
            <svg
              viewBox={`0 0 ${W} ${H}`}
              className="w-full"
              style={{ overflow: "visible" }}
              role="img"
              aria-label="P(evil) belief over time for each player"
            >
              {gridYs.map((v) => (
                <g key={v}>
                  <line
                    x1={PAD.left}
                    x2={W - PAD.right}
                    y1={yScale(v)}
                    y2={yScale(v)}
                    stroke="#2e2e3a"
                    strokeWidth="0.15"
                  />
                  <text
                    x={PAD.left - 1}
                    y={yScale(v) + 0.8}
                    textAnchor="end"
                    fill="#9a9aaa"
                    fontSize="2.2"
                    fontFamily="Plus Jakarta Sans, system-ui, sans-serif"
                  >
                    {v.toFixed(v % 0.5 === 0 ? 1 : 2)}
                  </text>
                </g>
              ))}

              {questMarkers.map((m) => (
                <g key={`qm-${m.quest}`}>
                  <line
                    x1={xScale(m.seq)}
                    x2={xScale(m.seq)}
                    y1={PAD.top}
                    y2={PAD.top + PLOT_H}
                    stroke={m.passed ? "#2e9e5b" : "#c42b2b"}
                    strokeWidth="0.2"
                    strokeDasharray="0.8 0.6"
                    opacity={0.6}
                  />
                  <text
                    x={xScale(m.seq)}
                    y={PAD.top + PLOT_H + 3.5}
                    textAnchor="middle"
                    fill="#9a9aaa"
                    fontSize="1.8"
                    fontFamily="Plus Jakarta Sans, system-ui, sans-serif"
                  >
                    Q{m.quest}
                  </text>
                </g>
              ))}

              {Array.from(linesByTarget.entries()).map(([target, points]) => {
                if (points.length < 2) return null;
                const d = points
                  .map(
                    (pt, i) =>
                      `${i === 0 ? "M" : "L"}${xScale(pt.seq).toFixed(2)},${yScale(pt.value).toFixed(2)}`
                  )
                  .join(" ");
                return (
                  <path
                    key={`line-${target}`}
                    d={d}
                    fill="none"
                    stroke={SEAT_COLORS[target] ?? "#9a9aaa"}
                    strokeWidth="0.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                );
              })}

              {Array.from(linesByTarget.entries()).map(([target, points]) => {
                const last = points[points.length - 1];
                return (
                  <g key={`dot-${target}`}>
                    <circle
                      cx={xScale(last.seq)}
                      cy={yScale(last.value)}
                      r="0.9"
                      fill="#1a1a24"
                      stroke={SEAT_COLORS[target] ?? "#9a9aaa"}
                      strokeWidth="0.35"
                    />
                    <text
                      x={xScale(last.seq) + 1.2}
                      y={yScale(last.value) + 0.7}
                      fill="#e8dcc8"
                      fontSize="2"
                      fontFamily="JetBrains Mono, monospace"
                    >
                      {last.value.toFixed(2)}
                    </text>
                  </g>
                );
              })}
            </svg>

            <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2">
              {Array.from(linesByTarget.entries()).map(([target, points]) => {
                const last = points[points.length - 1];
                return (
                  <div
                    key={`legend-${target}`}
                    className="flex items-center gap-1.5 text-xs font-body"
                  >
                    <span
                      className="inline-block w-3 h-[2px] rounded-full"
                      style={{ backgroundColor: SEAT_COLORS[target] }}
                    />
                    <span className="text-medieval-parchment-dim">P{target}</span>
                    <span className="text-medieval-parchment font-mono text-[10px]">
                      {last.value.toFixed(2)}
                    </span>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
