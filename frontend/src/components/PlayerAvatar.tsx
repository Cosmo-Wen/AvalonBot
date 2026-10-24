import { useEffect, useRef } from "react";
import { type Player, SEAT_NAMES, SEAT_COLORS, ROLE_DISPLAY } from "../types";

interface PlayerAvatarProps {
  player: Player;
  isLeader: boolean;
  isOnTeam: boolean;
  vote?: boolean;
  showRole: boolean;
  size?: number;
  videoStream?: MediaStream | null;
}

const SEAT_INITIALS = ["At", "Ly", "Gr", "Ph", "So"];
const SEAT_GRADIENT_PAIRS: [string, string][] = [
  ["#c9a84c", "#a08030"],  // Arthur — gold
  ["#6c9bff", "#4a6fcc"],  // Lancelot — blue
  ["#4cc27e", "#2e9e5b"],  // Guinevere — green
  ["#e0a83a", "#b8862e"],  // Percival — amber
  ["#a48bff", "#7b5fcc"],  // Galahad — purple
];

function PortraitSilhouette({ seat, size }: { seat: number; size: number }) {
  const [c1, c2] = SEAT_GRADIENT_PAIRS[seat % SEAT_GRADIENT_PAIRS.length];
  const gradientId = `seat-grad-${seat}`;
  return (
    <svg width={size} height={size} viewBox="0 0 60 60" fill="none">
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={c1} stopOpacity="0.25" />
          <stop offset="100%" stopColor={c2} stopOpacity="0.15" />
        </linearGradient>
      </defs>
      <circle cx="30" cy="30" r="28" fill={`url(#${gradientId})`} stroke={c1} strokeWidth="1" strokeOpacity="0.2" />
      <text
        x="30"
        y="33"
        textAnchor="middle"
        dominantBaseline="central"
        fill={c1}
        fillOpacity="0.85"
        fontSize="20"
        fontFamily="Cinzel, serif"
        fontWeight="600"
      >
        {SEAT_INITIALS[seat]}
      </text>
    </svg>
  );
}

function VoteToken({ approve }: { approve: boolean }) {
  if (approve) {
    return (
      <div className="animate-vote-in absolute -top-1 -right-1 z-10 w-7 h-7 rounded-full bg-medieval-good/90 flex items-center justify-center shadow-[0_0_12px_rgba(46,158,91,0.4)]">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <path d="M3 7l3 3 5-5" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
    );
  }
  return (
    <div className="animate-vote-in absolute -top-1 -right-1 z-10 w-7 h-7 rounded-full bg-medieval-crimson-bright/90 flex items-center justify-center shadow-[0_0_12px_rgba(196,43,43,0.4)]">
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <path d="M3 3l6 6M9 3l-6 6" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
      </svg>
    </div>
  );
}

function RoleBadge({ role, side }: { role: string; side?: string }) {
  const color =
    role === "merlin"
      ? "bg-medieval-merlin"
      : side === "evil"
        ? "bg-medieval-crimson-bright"
        : "bg-medieval-good";
  return (
    <div
      className={`absolute -bottom-0.5 left-1/2 -translate-x-1/2 ${color} rounded-full px-2 py-0.5 text-[9px] font-display uppercase tracking-[0.15em] text-white shadow-[0_2px_8px_rgba(0,0,0,0.4)]`}
    >
      {ROLE_DISPLAY[role as keyof typeof ROLE_DISPLAY] ?? role}
    </div>
  );
}

function AudioLevelBar({ level }: { level: number }) {
  return (
    <div className="absolute -bottom-4 left-1/2 -translate-x-1/2 flex gap-[2px]">
      {[0.2, 0.4, 0.6, 0.8, 1.0].map((threshold, i) => (
        <div
          key={i}
          className="w-[3px] rounded-full transition-all duration-150 ease-fluid"
          style={{
            height: level >= threshold ? `${8 + i * 2}px` : "3px",
            background:
              level >= threshold
                ? `rgba(201, 168, 76, ${0.5 + level * 0.5})`
                : "rgba(201, 168, 76, 0.15)",
          }}
        />
      ))}
    </div>
  );
}

function AvatarVideo({ stream, size }: { stream: MediaStream; size: number }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.srcObject = stream;
    }
  }, [stream]);
  return (
    <video
      ref={videoRef}
      autoPlay
      playsInline
      muted
      className="absolute inset-0 w-full h-full object-cover rounded-full"
      style={{ width: size, height: size }}
    />
  );
}

export default function PlayerAvatar({
  player,
  isLeader,
  isOnTeam,
  vote,
  showRole,
  size = 96,
  videoStream,
}: PlayerAvatarProps) {
  const innerSize = size - 12;
  const hasVideo = !!videoStream;

  return (
    <div className="flex flex-col items-center gap-2 select-none">
      {/* Double-Bezel (Doppelrand) frame — outer shell */}
      <div
        className={`relative rounded-full transition-all duration-700 ease-fluid ${
          player.isSpeaking ? "animate-glow-ring" : ""
        } ${isOnTeam ? "ring-2 ring-medieval-gold/50" : ""}`}
        style={{
          width: size,
          height: size,
          padding: "5px",
          background: player.isSpeaking
            ? "rgba(201, 168, 76, 0.1)"
            : "rgba(201, 168, 76, 0.04)",
          border: `1px solid ${
            player.isSpeaking
              ? "rgba(201, 168, 76, 0.35)"
              : isOnTeam
                ? "rgba(201, 168, 76, 0.25)"
                : "rgba(201, 168, 76, 0.1)"
          }`,
        }}
      >
        {/* Inner core */}
        <div
          className={`relative w-full h-full rounded-full overflow-hidden flex items-center justify-center transition-all duration-700 ease-fluid ${
            player.isSpeaking ? "animate-speak-pulse" : ""
          }`}
          style={{
            background: "#1c1c28",
            boxShadow: "inset 0 1px 2px rgba(201, 168, 76, 0.06)",
          }}
        >
          {hasVideo ? (
            <AvatarVideo stream={videoStream} size={innerSize} />
          ) : (
            <PortraitSilhouette seat={player.seat} size={innerSize * 0.7} />
          )}

          {/* Speaking overlay glow */}
          {player.isSpeaking && (
            <div
              className="absolute inset-0 rounded-full pointer-events-none"
              style={{
                background:
                  "radial-gradient(circle at 50% 40%, rgba(201, 168, 76, 0.12) 0%, transparent 65%)",
              }}
            />
          )}
        </div>

        {/* Vote token */}
        {vote !== undefined && <VoteToken approve={vote} />}

        {/* Leader crown indicator */}
        {isLeader && (
          <div className="absolute -top-3 left-1/2 -translate-x-1/2">
            <svg width="20" height="16" viewBox="0 0 20 16" fill="none">
              <path
                d="M2 14L0 4l5 4 5-6 5 6 5-4-2 10H2z"
                fill="#c9a84c"
                fillOpacity="0.9"
                stroke="#e8c95a"
                strokeWidth="0.5"
              />
              <circle cx="5" cy="10" r="1" fill="#e8c95a" />
              <circle cx="10" cy="9" r="1" fill="#e8c95a" />
              <circle cx="15" cy="10" r="1" fill="#e8c95a" />
            </svg>
          </div>
        )}

        {/* Role badge */}
        {showRole && player.role && (
          <RoleBadge role={player.role} side={player.side} />
        )}

        {/* Audio level indicator */}
        {player.isSpeaking && player.audioLevel > 0 && (
          <AudioLevelBar level={player.audioLevel} />
        )}
      </div>

      {/* Player name */}
      <div className="text-center">
        <div
          className={`font-display text-xs uppercase tracking-[0.15em] transition-colors duration-500 ease-fluid ${
            player.isSpeaking
              ? "text-medieval-gold"
              : "text-medieval-parchment-dim"
          }`}
        >
          {SEAT_NAMES[player.seat]}
        </div>
        <div className="font-body text-[10px] text-medieval-silver/50">
          Seat {player.seat}
        </div>
      </div>
    </div>
  );
}
