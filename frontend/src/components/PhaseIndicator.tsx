import { type GamePhase } from "../types";

interface PhaseIndicatorProps {
  phase: GamePhase;
  details: string;
  winner?: "good" | "evil" | null;
}

const PHASE_LABELS: Record<GamePhase, string> = {
  waiting: "Awaiting Game",
  team_selection: "Team Selection",
  team_voting: "Team Voting",
  quest_voting: "Quest Voting",
  assassination: "Assassination",
  game_over: "Game Over",
};

export default function PhaseIndicator({
  phase,
  details,
  winner,
}: PhaseIndicatorProps) {
  const isGameOver = phase === "game_over";
  const isAssassination = phase === "assassination";

  const bannerColor = isGameOver
    ? winner === "good"
      ? "rgba(46, 158, 91, 0.12)"
      : "rgba(196, 43, 43, 0.12)"
    : isAssassination
      ? "rgba(196, 43, 43, 0.08)"
      : "rgba(201, 168, 76, 0.06)";

  const borderColor = isGameOver
    ? winner === "good"
      ? "rgba(46, 158, 91, 0.25)"
      : "rgba(196, 43, 43, 0.25)"
    : isAssassination
      ? "rgba(196, 43, 43, 0.15)"
      : "rgba(201, 168, 76, 0.12)";

  const textColor = isGameOver
    ? winner === "good"
      ? "text-medieval-good"
      : "text-medieval-evil"
    : isAssassination
      ? "text-medieval-crimson-bright"
      : "text-medieval-gold";

  return (
    <div
      className="animate-fade-up flex flex-col items-center gap-1 py-2 px-6 relative"
      style={{
        background: bannerColor,
        borderBottom: `1px solid ${borderColor}`,
      }}
    >
      <div
        className="absolute left-0 top-0 w-6 h-full"
        style={{
          background:
            "linear-gradient(90deg, transparent 0%, transparent 40%, transparent 100%)",
          clipPath: "polygon(0 0, 100% 20%, 100% 80%, 0 100%)",
          borderRight: `1px solid ${borderColor}`,
        }}
      />
      <div
        className="absolute right-0 top-0 w-6 h-full"
        style={{
          clipPath: "polygon(0 20%, 100% 0, 100% 100%, 0 80%)",
          borderLeft: `1px solid ${borderColor}`,
        }}
      />

      <span
        className={`font-display text-sm font-bold uppercase tracking-[0.2em] ${textColor}`}
      >
        {PHASE_LABELS[phase]}
      </span>

      {details && (
        <span className="text-medieval-parchment-dim text-xs font-body">
          {details}
        </span>
      )}

      {isGameOver && winner && (
        <span
          className={`mt-1 font-display text-lg font-bold uppercase tracking-wider ${textColor}`}
          style={{
            textShadow:
              winner === "good"
                ? "0 0 20px rgba(46, 158, 91, 0.3)"
                : "0 0 20px rgba(196, 43, 43, 0.3)",
          }}
        >
          {winner === "good" ? "Good Prevails" : "Evil Triumphs"}
        </span>
      )}
    </div>
  );
}
