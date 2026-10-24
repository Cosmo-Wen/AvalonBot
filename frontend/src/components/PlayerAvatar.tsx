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

const SILHOUETTES: string[] = [
  // Seat 0 — crowned king profile
  "M24 14c0-3.5-2.5-6-6-6s-6 2.5-6 6c0 1.8.8 3.4 2 4.5V22c-3 1-7 3.5-7 7v5h22v-5c0-3.5-4-6-7-7v-3.5c1.2-1.1 2-2.7 2-4.5zm-6-9l-3 4h6l-3-4zm-5 4l-1.5 3h13l-1.5-3h-10z",
  // Seat 1 — knight helm profile
  "M14 10c0-2.2 1.8-4 4-4s4 1.8 4 4v2h2c1.1 0 2 .9 2 2v6c0 1.1-.9 2-2 2h-1v2c-2.5 1.5-6 3-6 3s-3.5-1.5-6-3v-2h-1c-1.1 0-2-.9-2-2v-6c0-1.1.9-2 2-2h2v-2zm-3 8h14v-2H11v2z",
  // Seat 2 — hooded figure (Guinevere)
  "M18 8c-5 0-9 3-10 7-1 4 0 5 2 6v3c-3 1.5-5 3.5-5 6v4h26v-4c0-2.5-2-4.5-5-6v-3c2-1 3-2 2-6-1-4-5-7-10-7zm0 3c2 0 3.5 1 4 3h-8c.5-2 2-3 4-3z",
  // Seat 3 — wise elder (bearded)
  "M18 8c-3.3 0-6 2.7-6 6 0 1.5.6 2.9 1.5 4-.5.5-1 1.2-1 2v4c-3 1.5-5.5 3.5-5.5 6v4h22v-4c0-2.5-2.5-4.5-5.5-6v-4c0-.8-.5-1.5-1-2 .9-1.1 1.5-2.5 1.5-4 0-3.3-2.7-6-6-6zm-2 16c-.5 1-1 2.5-1 4h-2c0-2.5 1-3.5 3-4zm4 0c2 .5 3 1.5 3 4h-2c0-1.5-.5-3-1-4z",
  // Seat 4 — young knight
  "M18 9c-3 0-5.5 2.5-5.5 5.5 0 1.7.8 3.2 2 4.2v2.8c-4 1.5-7 4-7 7v5.5h21v-5.5c0-3-3-5.5-7-7v-2.8c1.2-1 2-2.5 2-4.2 0-3-2.5-5.5-5.5-5.5zm-4-3l4-3 4 3h-8z",
];

function PortraitSilhouette({ seat, size }: { seat: number; size: number }) {
  const scale = size / 36;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 36 36"
      fill="none"
      className="opacity-60"
    >
      <path
        d={SILHOUETTES[seat % SILHOUETTES.length]}
        fill={SEAT_COLORS[seat]}
        fillOpacity="0.7"
        transform={`scale(${scale > 1 ? 1 : scale})`}
      />
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
