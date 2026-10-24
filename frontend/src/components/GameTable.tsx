import PlayerAvatar from "./PlayerAvatar";
import { type Player, type TeamProposal } from "../types";

interface GameTableProps {
  players: Player[];
  leader: number;
  proposal: TeamProposal | null;
  showRoles: boolean;
  seatVideos?: Record<number, { stream: MediaStream }>;
}

// Positions around a circle — evenly spaced, starting from top center
// Each avatar is centered on its point via translate(-50%, -50%)
const AVATAR_POSITIONS = [
  { top: "4%", left: "50%" },   // Seat 0 — top center
  { top: "28%", left: "93%" },  // Seat 1 — upper right
  { top: "78%", left: "80%" },  // Seat 2 — lower right
  { top: "78%", left: "20%" },  // Seat 3 — lower left
  { top: "28%", left: "7%" },   // Seat 4 — upper left
];

export default function GameTable({
  players,
  leader,
  proposal,
  showRoles,
  seatVideos,
}: GameTableProps) {
  const teamSet = new Set(proposal?.team ?? []);

  return (
    <div className="relative w-full max-w-[560px] mx-auto aspect-square">
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
          width: "55%",
          height: "55%",
          padding: "5px",
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
            className="absolute inset-0 w-full h-full object-cover scale-150"
            style={{ objectPosition: "50% 35%" }}
            draggable={false}
          />
          {/* Heavy vignette to hide text on the image */}
          <div
            className="absolute inset-0"
            style={{
              background:
                "radial-gradient(circle at 50% 50%, transparent 20%, rgba(10, 10, 15, 0.6) 50%, rgba(10, 10, 15, 0.92) 75%, rgba(10, 10, 15, 1) 100%)",
            }}
          />
          {/* Inner glow for depth */}
          <div
            className="absolute inset-0"
            style={{
              background:
                "radial-gradient(circle at 50% 50%, rgba(201, 168, 76, 0.06) 0%, transparent 40%)",
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
              top: pos.top,
              left: pos.left,
              transform: "translate(-50%, -50%)",
              transition: "all 700ms cubic-bezier(0.32, 0.72, 0, 1)",
            }}
          >
            <PlayerAvatar
              player={player}
              isLeader={leader === player.seat}
              isOnTeam={teamSet.has(player.seat)}
              vote={proposal?.votes?.[player.seat]}
              showRole={showRoles}
              size={88}
              videoStream={seatVideos?.[player.seat]?.stream ?? null}
            />
          </div>
        );
      })}
    </div>
  );
}
