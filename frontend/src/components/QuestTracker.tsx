import { type QuestResult, QUEST_SIZES } from "../types";

interface QuestTrackerProps {
  quests: (QuestResult | null)[];
  currentQuest: number;
}

function QuestShield({
  result,
  index,
  isActive,
}: {
  result: QuestResult | null;
  index: number;
  isActive: boolean;
}) {
  const teamSize = QUEST_SIZES[index];
  const isPassed = result !== null && result.success;
  const isFailed = result !== null && !result.success;
  const isPending = result === null;

  const fillColor = isPassed
    ? "rgba(46, 158, 91, 0.2)"
    : isFailed
      ? "rgba(196, 43, 43, 0.2)"
      : "rgba(34, 34, 46, 0.6)";

  const strokeColor = isPassed
    ? "#4cc27e"
    : isFailed
      ? "#f06a6a"
      : isActive
        ? "#c9a84c"
        : "#2e2e3a";

  return (
    <div className="flex flex-col items-center gap-1.5">
      <div
        className={`relative transition-all duration-700 ease-[cubic-bezier(0.32,0.72,0,1)] ${
          isActive ? "animate-glow-ring rounded-full" : ""
        }`}
      >
        <svg width="40" height="48" viewBox="0 0 40 48" fill="none">
          <path
            d="M20 2L4 10V24C4 34 12 42 20 46C28 42 36 34 36 24V10L20 2Z"
            fill={fillColor}
            stroke={strokeColor}
            strokeWidth={isActive ? "2" : "1.5"}
            strokeLinejoin="round"
            style={{
              transition: "all 700ms cubic-bezier(0.32, 0.72, 0, 1)",
            }}
          />
          <path
            d="M20 6L8 12V24C8 32 14 38 20 42C26 38 32 32 32 24V12L20 6Z"
            stroke={strokeColor}
            strokeWidth="0.4"
            strokeOpacity="0.25"
            strokeLinejoin="round"
          />

          {isPassed && (
            <path
              d="M14 22L18 26L26 18"
              stroke="#4cc27e"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="animate-fade-up"
            />
          )}

          {isFailed && (
            <g className="animate-fade-up">
              <path
                d="M15 18L25 28"
                stroke="#f06a6a"
                strokeWidth="2.5"
                strokeLinecap="round"
              />
              <path
                d="M25 18L15 28"
                stroke="#f06a6a"
                strokeWidth="2.5"
                strokeLinecap="round"
              />
            </g>
          )}

          {isPending && (
            <text
              x="20"
              y="26"
              textAnchor="middle"
              fill={isActive ? "#c9a84c" : "#9a9aaa"}
              fontSize="13"
              fontWeight="600"
              fontFamily="Cinzel, serif"
            >
              {index + 1}
            </text>
          )}
        </svg>

        {isActive && (
          <div
            className="absolute -inset-1 rounded-full pointer-events-none"
            style={{
              background:
                "radial-gradient(circle, rgba(201, 168, 76, 0.12) 0%, transparent 70%)",
            }}
          />
        )}
      </div>

      <span
        title={`Team of ${teamSize}`}
        className={`whitespace-nowrap font-mono text-[10px] transition-colors duration-500 ${
          isActive
            ? "text-medieval-gold"
            : isPassed
              ? "text-medieval-good"
              : isFailed
                ? "text-medieval-evil"
                : "text-medieval-silver/50"
        }`}
      >
        team {teamSize}
      </span>

      {isFailed && result !== null && result.numFails > 0 && (
        <span className="text-[9px] text-medieval-evil/70 font-mono">
          {result.numFails} fail{result.numFails !== 1 ? "s" : ""}
        </span>
      )}
    </div>
  );
}

export default function QuestTracker({
  quests,
  currentQuest,
}: QuestTrackerProps) {
  const goodWins = quests.filter((q) => q !== null && q.success).length;
  const evilWins = quests.filter((q) => q !== null && !q.success).length;

  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-medieval-border bg-medieval-darker p-4">
      <div className="flex items-center justify-between">
        <span className="font-display text-xs uppercase tracking-[0.2em] text-medieval-good">Good {goodWins}</span>
        <span className="font-display text-[10px] uppercase tracking-[0.2em] text-medieval-gold-dim">Quests</span>
        <span className="font-display text-xs uppercase tracking-[0.2em] text-[#f06a6a]">Evil {evilWins}</span>
      </div>
      <div className="flex items-start justify-between">
        {quests.map((result, i) => (
          <QuestShield key={i} result={result} index={i} isActive={i === currentQuest - 1 && result === null} />
        ))}
      </div>
    </div>
  );
}
