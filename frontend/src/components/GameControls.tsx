interface GameControlsProps {
  isPlaying: boolean;
  speed: number;
  onPlayPause: () => void;
  onStep: () => void;
  onSpeedChange: (speed: number) => void;
  onNewGame: () => void;
  onLoadReplay: (file: string) => void;
  progress: {
    current: number;
    total: number;
    quest: number;
    round: number;
  };
  availableReplays: string[];
}

const SPEED_OPTIONS = [0.5, 1, 2, 4] as const;

function ControlButton({
  children,
  onClick,
  active = false,
  compact = false,
}: {
  children: React.ReactNode;
  onClick: () => void;
  active?: boolean;
  compact?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={`group rounded-full font-body text-xs font-medium transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)] active:scale-[0.96] ${
        compact ? "px-3 py-1.5" : "px-4 py-2"
      } ${
        active
          ? "bg-medieval-gold/15 text-medieval-gold border border-medieval-gold/30"
          : "bg-medieval-surface/80 text-medieval-silver/70 border border-medieval-border/40 hover:text-medieval-parchment hover:border-medieval-border"
      }`}
    >
      {children}
    </button>
  );
}

export default function GameControls({
  isPlaying,
  speed,
  onPlayPause,
  onStep,
  onSpeedChange,
  onNewGame,
  onLoadReplay,
  progress,
  availableReplays,
}: GameControlsProps) {
  return (
    <div
      className="flex items-center justify-between gap-4 px-6 py-3 border-t border-medieval-border/30"
      style={{
        background:
          "linear-gradient(180deg, rgba(17, 17, 24, 0.95) 0%, rgba(10, 10, 15, 0.98) 100%)",
      }}
    >
      <div className="flex items-center gap-2">
        <ControlButton onClick={onPlayPause} active={isPlaying}>
          <span className="flex items-center gap-1.5">
            {isPlaying ? (
              <svg
                width="12"
                height="12"
                viewBox="0 0 12 12"
                fill="none"
                className="transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]"
              >
                <rect
                  x="2"
                  y="1"
                  width="3"
                  height="10"
                  rx="0.5"
                  fill="currentColor"
                />
                <rect
                  x="7"
                  y="1"
                  width="3"
                  height="10"
                  rx="0.5"
                  fill="currentColor"
                />
              </svg>
            ) : (
              <svg
                width="12"
                height="12"
                viewBox="0 0 12 12"
                fill="none"
                className="transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]"
              >
                <path d="M2 1L10 6L2 11V1Z" fill="currentColor" />
              </svg>
            )}
            {isPlaying ? "Pause" : "Play"}
          </span>
        </ControlButton>

        <ControlButton onClick={onStep} compact>
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <path d="M2 1L7 6L2 11V1Z" fill="currentColor" />
            <rect
              x="8"
              y="1"
              width="2"
              height="10"
              rx="0.5"
              fill="currentColor"
            />
          </svg>
        </ControlButton>

        <div className="flex items-center gap-1 ml-2">
          {SPEED_OPTIONS.map((s) => (
            <button
              key={s}
              onClick={() => onSpeedChange(s)}
              className={`px-2 py-1 rounded-md text-[10px] font-mono font-medium transition-all duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] active:scale-[0.95] ${
                speed === s
                  ? "text-medieval-gold bg-medieval-gold/10"
                  : "text-medieval-silver/40 hover:text-medieval-silver/70"
              }`}
            >
              {s}x
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-4">
        <div className="flex items-center gap-3 text-medieval-silver/50 font-mono text-[11px]">
          <span>
            Event{" "}
            <span className="text-medieval-parchment/80">
              {progress.current}
            </span>
            /{progress.total}
          </span>
          <span className="w-px h-3 bg-medieval-border/30" />
          <span>
            Quest{" "}
            <span className="text-medieval-parchment/80">
              {progress.quest + 1}
            </span>
            , Round{" "}
            <span className="text-medieval-parchment/80">
              {progress.round + 1}
            </span>
          </span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        {availableReplays.length > 0 && (
          <select
            onChange={(e) => {
              if (e.target.value) onLoadReplay(e.target.value);
            }}
            defaultValue=""
            className="bg-medieval-surface/80 text-medieval-silver/70 border border-medieval-border/40 rounded-full px-3 py-1.5 text-xs font-body appearance-none cursor-pointer transition-all duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] hover:border-medieval-border focus:outline-none focus:border-medieval-gold/30"
          >
            <option value="" disabled>
              Load replay
            </option>
            {availableReplays.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        )}

        <ControlButton onClick={onNewGame}>
          <span className="flex items-center gap-1.5">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
              <circle
                cx="6"
                cy="6"
                r="4.5"
                stroke="currentColor"
                strokeWidth="1.2"
              />
              <path
                d="M6 3.5V6L8 7.5"
                stroke="currentColor"
                strokeWidth="1"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            New Game
          </span>
        </ControlButton>
      </div>
    </div>
  );
}
