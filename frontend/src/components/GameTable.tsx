import { useEffect, useRef, useState, type ReactNode } from "react";
import PlayerAvatar from "./PlayerAvatar";
import type { Player, TeamProposal } from "../types";

interface GameTableProps {
  players: Player[];
  leader: number;
  proposal: TeamProposal | null;
  showRoles: boolean;
  seatVideos: Record<number, MediaStream>;
  levels: Record<number, number>;
  children?: ReactNode;
}

const TABLE_DIAMETER = 0.6;
const SEAT_RADIUS = 0.39;

function seatPosition(seat: number) {
  const angle = -Math.PI / 2 + (2 * Math.PI * seat) / 5;
  return { left: 50 + SEAT_RADIUS * 100 * Math.cos(angle), top: 50 + SEAT_RADIUS * 100 * Math.sin(angle) };
}

export default function GameTable({ players, leader, proposal, showRoles, seatVideos, levels, children }: GameTableProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState(640);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => setSize(entry.contentRect.width));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);

  const team = new Set(proposal?.team ?? []);
  const avatarWidth = Math.max(78, Math.min(132, size * 0.16));

  return (
    <div ref={ref} className="relative mx-auto aspect-square w-full max-w-[760px]">
      <div
        className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full"
        style={{ width: `${TABLE_DIAMETER * 100 + 4}%`, height: `${TABLE_DIAMETER * 100 + 4}%`, background: "radial-gradient(circle, rgba(201,168,76,0.12) 55%, transparent 72%)" }}
      />
      <img
        src="/round-table.webp"
        alt="The Round Table"
        draggable={false}
        className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full"
        style={{ width: `${TABLE_DIAMETER * 100}%`, height: `${TABLE_DIAMETER * 100}%`, filter: "saturate(0.9) brightness(0.92)" }}
      />

      <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center">{children}</div>

      {players.map((player) => {
        const pos = seatPosition(player.seat);
        return (
          <div
            key={player.seat}
            className="absolute z-10 -translate-x-1/2 -translate-y-1/2"
            style={{ left: `${pos.left}%`, top: `${pos.top}%` }}
          >
            <PlayerAvatar
              player={player}
              isLeader={leader === player.seat}
              isOnTeam={team.has(player.seat)}
              vote={proposal?.votes?.[player.seat]}
              showRole={showRoles}
              videoStream={seatVideos[player.seat] ?? null}
              level={levels[player.seat] ?? 0}
              width={avatarWidth}
            />
          </div>
        );
      })}
    </div>
  );
}
