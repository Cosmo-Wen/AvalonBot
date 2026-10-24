import { useEffect, useRef } from "react";
import type { RemoteTrack } from "livekit-client";
import { type Player, ROLE_DISPLAY, SEAT_COLORS, seatName } from "../types";

interface PlayerAvatarProps {
  player: Player;
  isLeader: boolean;
  isOnTeam: boolean;
  vote?: boolean;
  showRole: boolean;
  videoTrack?: RemoteTrack | null;
  audioTrack?: RemoteTrack | null;
  muted?: boolean;
  level: number;
  width: number;
}

const ROLE_ICON: Record<string, string> = {
  merlin: "/roles/merlin-icon.webp",
  assassin: "/roles/assassin-icon.webp",
  minion: "/roles/evil-icon.webp",
  loyal_servant: "/roles/good-icon.webp",
};

function AvatarVideo({ video, audio, muted }: { video: RemoteTrack; audio?: RemoteTrack | null; muted: boolean }) {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Both tracks go on one element so the mouth and the voice share a clock.
    video.attach(el);
    audio?.attach(el);
    el.muted = muted;
    el.play().catch(() => undefined);
    return () => {
      video.detach(el);
      audio?.detach(el);
    };
  }, [video, audio, muted]);
  return <video ref={ref} autoPlay playsInline className="absolute inset-0 h-full w-full object-cover object-top" />;
}

function Emblem({ seat }: { seat: number }) {
  const color = SEAT_COLORS[seat];
  return (
    <div className="absolute inset-0 flex items-center justify-center">
      <svg viewBox="0 0 60 72" className="h-[70%] w-[70%]" fill="none">
        <path d="M30 3L6 13V35C6 50 17 62 30 69C43 62 54 50 54 35V13L30 3Z" fill={color} fillOpacity="0.08" stroke={color} strokeOpacity="0.5" strokeWidth="1.2" />
        <path d="M30 9L11 17V35C11 47 19 57 30 63C41 57 49 47 49 35V17L30 9Z" stroke={color} strokeOpacity="0.2" strokeWidth="0.6" />
        <text x="30" y="44" textAnchor="middle" fill={color} fontSize="22" fontFamily="Cinzel, serif" fontWeight="700">
          {seatName(seat)[0]}
        </text>
      </svg>
    </div>
  );
}

export default function PlayerAvatar({ player, isLeader, isOnTeam, vote, showRole, videoTrack, audioTrack, muted = false, level, width }: PlayerAvatarProps) {
  const color = SEAT_COLORS[player.seat];
  const speaking = player.isSpeaking || level > 0.05;
  const height = Math.round(width * 1.25);
  const evil = player.side === "evil";

  return (
    <div className="flex select-none flex-col items-center gap-1.5" style={{ width }}>
      <div
        className="relative overflow-visible rounded-2xl transition-all duration-500 ease-fluid"
        style={{
          width,
          height,
          padding: 3,
          background: speaking ? `${color}33` : "rgba(201,168,76,0.05)",
          border: `1.5px solid ${speaking ? color : isOnTeam ? "rgba(201,168,76,0.7)" : "rgba(201,168,76,0.14)"}`,
          transform: speaking ? "scale(1.05)" : "scale(1)",
        }}
      >
        <div className="relative h-full w-full overflow-hidden rounded-[0.8rem] bg-medieval-surface">
          {videoTrack ? <AvatarVideo video={videoTrack} audio={audioTrack} muted={muted} /> : <Emblem seat={player.seat} />}
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-black/70 to-transparent" />
          {speaking && (
            <div className="absolute bottom-1.5 left-1/2 flex -translate-x-1/2 items-end gap-[2px]">
              {[0.15, 0.3, 0.5, 0.3, 0.15].map((t, i) => (
                <span
                  key={i}
                  className="w-[3px] rounded-full transition-all duration-100"
                  style={{ height: 4 + Math.max(0, (level || 0.4) - t) * 22, background: color }}
                />
              ))}
            </div>
          )}
        </div>

        {isLeader && (
          <div className="absolute -top-3.5 left-1/2 -translate-x-1/2" title="Leader">
            <svg width="26" height="20" viewBox="0 0 20 16" fill="none">
              <path d="M2 14L0 4l5 4 5-6 5 6 5-4-2 10H2z" fill="#c9a84c" stroke="#e8c95a" strokeWidth="0.6" />
            </svg>
          </div>
        )}

        {isOnTeam && (
          <div className="absolute -left-2 -top-2 rounded-full border border-medieval-gold/60 bg-medieval-black px-1.5 py-0.5 text-[9px] font-display uppercase tracking-[0.12em] text-medieval-gold">
            Quest
          </div>
        )}

        {vote !== undefined && (
          <div
            className={`animate-vote-in absolute -right-2.5 -top-2.5 flex h-8 w-8 items-center justify-center rounded-full border-2 ${
              vote ? "border-medieval-good bg-medieval-good/90" : "border-medieval-crimson-bright bg-medieval-crimson-bright/90"
            }`}
            title={vote ? "Approved" : "Rejected"}
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              {vote ? (
                <path d="M3 7l3 3 5-5" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
              ) : (
                <path d="M4 4l6 6M10 4l-6 6" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" />
              )}
            </svg>
          </div>
        )}

        {showRole && player.role && (
          <div
            className={`absolute -bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1 whitespace-nowrap rounded-full border py-0.5 pl-0.5 pr-2 text-[10px] font-display uppercase tracking-[0.1em] ${
              evil ? "border-medieval-crimson-bright/60 bg-[#2a0d0d] text-[#f08a8a]" : player.role === "merlin" ? "border-medieval-merlin/60 bg-[#1b1433] text-[#c3b3ff]" : "border-medieval-good/60 bg-[#0d2418] text-[#7fd9a4]"
            }`}
          >
            <img src={ROLE_ICON[player.role]} alt="" className="h-5 w-5 rounded-full object-cover" draggable={false} />
            {ROLE_DISPLAY[player.role]}
          </div>
        )}
      </div>

      <div className={`text-center ${showRole && player.role ? "mt-2" : ""}`}>
        <div className="font-display text-xs uppercase tracking-[0.15em]" style={{ color: speaking ? color : "#b8a88a" }}>
          {player.name}
        </div>
        <div className="font-mono text-[10px] text-medieval-silver/60">P{player.seat}</div>
      </div>
    </div>
  );
}
