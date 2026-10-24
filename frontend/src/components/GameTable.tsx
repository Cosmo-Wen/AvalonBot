import PlayerAvatar from "./PlayerAvatar";
import { type Player, type TeamProposal } from "../types";

interface GameTableProps {
  players: Player[];
  leader: number;
  proposal: TeamProposal | null;
  showRoles: boolean;
  seatVideos?: Record<number, { stream: MediaStream }>;
}

const AVATAR_POSITIONS = [
  { top: "2%", left: "50%", transform: "translateX(-50%)" },
  { top: "22%", right: "2%" },
  { bottom: "10%", right: "10%" },
  { bottom: "10%", left: "10%" },
  { top: "22%", left: "2%" },
] as const;

export default function GameTable({
  players,
  leader,
  proposal,
  showRoles,
  seatVideos,
}: GameTableProps) {
  const teamSet = new Set(proposal?.team ?? []);

  return (
    <div className="relative w-full max-w-[640px] mx-auto aspect-square">
      {/* Ambient radial glow behind the table */}
      <div
        className="absolute inset-0 rounded-full pointer-events-none"
        style={{
          background:
            "radial-gradient(circle at 50% 50%, rgba(201, 168, 76, 0.06) 0%, transparent 55%)",
        }}
      />

      {/* Double-Bezel table frame — outer shell */}
      <div
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full"
        style={{
          width: "62%",
          height: "62%",
          padding: "6px",
          background: "rgba(201, 168, 76, 0.05)",
          border: "1px solid rgba(201, 168, 76, 0.12)",
        }}
      >
        {/* Inner core — the Round Table image */}
        <div
          className="w-full h-full rounded-full overflow-hidden relative"
          style={{
            boxShadow:
              "inset 0 2px 4px rgba(201, 168, 76, 0.08), 0 0 60px rgba(201, 168, 76, 0.05)",
          }}
        >
          <img
            src="/table.jpg"
            alt="The Round Table"
            className="w-full h-full object-cover"
            draggable={false}
          />
          {/* Radial gradient overlay to blend into the dark background */}
          <div
            className="absolute inset-0"
            style={{
              background:
                "radial-gradient(circle at 50% 50%, transparent 40%, rgba(10, 10, 15, 0.7) 75%, rgba(10, 10, 15, 0.95) 100%)",
            }}
          />
          {/* Inner vignette for depth */}
          <div
            className="absolute inset-0"
            style={{
              background:
                "radial-gradient(circle at 50% 50%, rgba(201, 168, 76, 0.03) 0%, transparent 50%)",
            }}
          />
        </div>
      </div>

      {/* Player avatars positioned around the table */}
      {players.map((player, i) => {
        const pos = AVATAR_POSITIONS[i];
        return (
          <div
            key={player.seat}
            className="absolute z-10"
            style={{
              ...pos,
              transition: "all 700ms cubic-bezier(0.32, 0.72, 0, 1)",
            }}
          >
            <PlayerAvatar
              player={player}
              isLeader={leader === player.seat}
              isOnTeam={teamSet.has(player.seat)}
              vote={proposal?.votes?.[player.seat]}
              showRole={showRoles}
              size={96}
              videoStream={seatVideos?.[player.seat]?.stream ?? null}
            />
          </div>
        );
      })}

      {/* Center phase label (optional — rendered by parent) */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-20 pointer-events-none" />
    </div>
  );
}
