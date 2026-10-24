import { type GameEvent, SEAT_COLORS, seatName } from "../types";

interface VoteOverlayProps {
  events: GameEvent[];
}

function Plate({ children, tone = "gold" }: { children: React.ReactNode; tone?: "gold" | "good" | "evil" }) {
  const border = tone === "good" ? "rgba(76,194,126,0.45)" : tone === "evil" ? "rgba(240,106,106,0.45)" : "rgba(201,168,76,0.35)";
  return (
    <div
      className="animate-fade-up flex max-w-[46%] flex-col items-center gap-2 rounded-2xl px-5 py-3 text-center backdrop-blur-sm"
      style={{ background: "rgba(10,10,15,0.82)", border: `1px solid ${border}` }}
    >
      {children}
    </div>
  );
}

function TeamChips({ team }: { team: number[] }) {
  return (
    <div className="flex flex-wrap items-center justify-center gap-1.5">
      {team.map((seat) => (
        <span
          key={seat}
          className="rounded-full border px-2 py-0.5 font-display text-[11px]"
          style={{ borderColor: SEAT_COLORS[seat], color: SEAT_COLORS[seat], background: `${SEAT_COLORS[seat]}14` }}
        >
          {seatName(seat)}
        </span>
      ))}
    </div>
  );
}

export default function VoteOverlay({ events }: VoteOverlayProps) {
  const last = [...events].reverse().find((e) => e.type !== "utterance" && e.type !== "evil_chat");
  if (!last) return null;
  return <div key={last.seq} className="contents">{renderEvent(last)}</div>;
}

function renderEvent(last: GameEvent) {
  const label = "font-display text-[10px] uppercase tracking-[0.22em] text-medieval-gold-dim";

  switch (last.type) {
    case "team_proposed":
      return (
        <Plate>
          <span className={label}>Quest {last.quest} · Proposal {last.round + 1}{last.round === 4 ? " (hammer)" : ""}</span>
          <span className="font-body text-xs text-medieval-parchment-dim">
            <span style={{ color: SEAT_COLORS[last.leader] }}>{seatName(last.leader)}</span> proposes
          </span>
          <TeamChips team={last.team} />
          <span className="font-body text-[11px] text-medieval-silver/70">Voting…</span>
        </Plate>
      );
    case "team_vote_result": {
      const yes = Object.values(last.votes).filter(Boolean).length;
      return (
        <Plate tone={last.approved ? "good" : "evil"}>
          <span className={label}>Quest {last.quest} · Proposal {last.round + 1}</span>
          <span className={`font-display text-base font-bold uppercase tracking-wider ${last.approved ? "text-medieval-good" : "text-[#f06a6a]"}`}>
            {last.approved ? "Team approved" : "Team rejected"}
          </span>
          <span className="font-mono text-xs text-medieval-parchment-dim">
            {yes} approve · {5 - yes} reject
          </span>
        </Plate>
      );
    }
    case "quest_result":
      return (
        <Plate tone={last.success ? "good" : "evil"}>
          <span className={label}>Quest {last.quest}</span>
          <img src={last.success ? "/ui/quest-success.webp" : "/ui/quest-fail.webp"} alt="" className="h-14 w-14 object-contain" />
          <span className={`font-display text-lg font-bold uppercase tracking-wider ${last.success ? "text-medieval-good" : "text-[#f06a6a]"}`}>
            {last.success ? "Succeeded" : "Failed"}
          </span>
          {!last.success && <span className="font-mono text-xs text-[#f06a6a]/80">{last.numFails} fail card{last.numFails === 1 ? "" : "s"}</span>}
          <TeamChips team={last.team} />
        </Plate>
      );
    case "assassination":
      return (
        <Plate tone={last.hitMerlin ? "evil" : "good"}>
          <span className={label}>Assassination</span>
          <span className="font-body text-sm text-medieval-parchment">
            {seatName(last.assassin)} strikes at {seatName(last.target)}
          </span>
          <span className={`font-display text-base font-bold uppercase ${last.hitMerlin ? "text-[#f06a6a]" : "text-medieval-good"}`}>
            {last.hitMerlin ? "Merlin has fallen" : "Merlin survives"}
          </span>
        </Plate>
      );
    case "game_over":
      return (
        <Plate tone={last.winner === "good" ? "good" : "evil"}>
          <img src={last.winner === "good" ? "/ui/victory.webp" : "/ui/defeat.webp"} alt="" className="h-16 w-16 object-contain" />
          <span className={`font-display text-xl font-bold uppercase tracking-wider ${last.winner === "good" ? "text-medieval-good" : "text-[#f06a6a]"}`}>
            {last.winner === "good" ? "Good prevails" : "Evil triumphs"}
          </span>
          {last.reason && <span className="font-body text-xs text-medieval-parchment-dim">{last.reason}</span>}
        </Plate>
      );
  }
}
