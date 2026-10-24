import { useState } from "react";

interface GameControlsProps {
  isPlaying: boolean;
  hasGame: boolean;
  speed: number;
  voiceOn: boolean;
  onPlayPause: () => void;
  onStep: () => void;
  onSpeedChange: (speed: number) => void;
  onVoiceToggle: () => void;
  onNewGame: () => void;
  onLoadReplay: (file: string) => void;
  status: string;
  availableReplays: string[];
}

const SPEED_OPTIONS = [0.5, 1, 2, 4] as const;

function Button({ children, onClick, active = false, disabled = false, title }: {
  children: React.ReactNode;
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`rounded-full border px-4 py-2 font-body text-xs font-medium transition-all duration-300 ease-fluid active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-40 ${
        active
          ? "border-medieval-gold/40 bg-medieval-gold/15 text-medieval-gold"
          : "border-medieval-border bg-medieval-surface/80 text-medieval-parchment-dim hover:border-medieval-border-bright hover:text-medieval-parchment"
      }`}
    >
      {children}
    </button>
  );
}

const replayLabel = (path: string) => {
  const parts = path.split("/");
  const i = parts.indexOf("games");
  return i > 0 ? `${parts[i - 1]} · ${parts[i + 1].replace(".jsonl", "")}` : path;
};

export default function GameControls(props: GameControlsProps) {
  const [replay, setReplay] = useState("");
  const chosen = replay || props.availableReplays[0] || "";

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-medieval-border/40 bg-medieval-deeper/95 px-6 py-3">
      <div className="flex items-center gap-2">
        <Button onClick={props.onPlayPause} active={props.isPlaying} disabled={!props.hasGame}>
          {props.isPlaying ? "Pause" : "Play"}
        </Button>
        <Button onClick={props.onStep} disabled={!props.hasGame} title="Advance one event">
          Step
        </Button>
        <div className="ml-2 flex items-center gap-1">
          {SPEED_OPTIONS.map((s) => (
            <button
              key={s}
              onClick={() => props.onSpeedChange(s)}
              className={`rounded-md px-2 py-1 font-mono text-[11px] transition-all duration-300 ${
                props.speed === s ? "bg-medieval-gold/10 text-medieval-gold" : "text-medieval-silver/60 hover:text-medieval-silver"
              }`}
            >
              {s}x
            </button>
          ))}
        </div>
        <Button onClick={props.onVoiceToggle} active={props.voiceOn} title="Speak each line with Higgs TTS (off above 2x)">
          Voice {props.voiceOn ? "on" : "off"}
        </Button>
      </div>

      <div className="font-mono text-[11px] text-medieval-silver/70">{props.status}</div>

      <div className="flex items-center gap-2">
        {props.availableReplays.length > 0 && (
          <>
            <select
              value={chosen}
              onChange={(e) => setReplay(e.target.value)}
              className="max-w-[260px] rounded-full border border-medieval-border bg-medieval-surface/80 px-3 py-2 font-body text-xs text-medieval-parchment-dim focus:border-medieval-gold/40 focus:outline-none"
            >
              {props.availableReplays.map((r) => (
                <option key={r} value={r}>{replayLabel(r)}</option>
              ))}
            </select>
            <Button onClick={() => chosen && props.onLoadReplay(chosen)}>Watch replay</Button>
          </>
        )}
        <Button onClick={props.onNewGame} active>
          New live game
        </Button>
      </div>
    </div>
  );
}
