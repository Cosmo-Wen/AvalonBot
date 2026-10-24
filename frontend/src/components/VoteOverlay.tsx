import { type TeamProposal, type GamePhase, SEAT_COLORS } from "../types";
import { SealApprove, SealReject } from "../assets/GameIcons";

interface VoteOverlayProps {
  proposal: TeamProposal | null;
  phase: GamePhase;
  questResult?: { success: boolean; numFails: number } | null;
}

function VoteToken({
  player,
  approve,
  index,
}: {
  player: number;
  approve: boolean;
  index: number;
}) {
  return (
    <div
      className="animate-vote-in"
      style={{ animationDelay: `${index * 80}ms` }}
    >
      <div className="flex flex-col items-center gap-1 transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)]">
        {approve ? (
          <SealApprove size={32} className="text-medieval-gold" />
        ) : (
          <SealReject size={32} className="text-medieval-silver/60" />
        )}
        <span
          className="text-[10px] font-mono font-medium"
          style={{ color: SEAT_COLORS[player] }}
        >
          P{player}
        </span>
      </div>
    </div>
  );
}

function TeamProposalDisplay({ proposal }: { proposal: TeamProposal }) {
  return (
    <div className="animate-fade-up flex flex-col items-center gap-2">
      <div className="flex items-center gap-2">
        <span
          className="rounded-full px-3 py-1 text-[10px] uppercase tracking-[0.2em] font-medium"
          style={{
            background: "rgba(201, 168, 76, 0.1)",
            border: "1px solid rgba(201, 168, 76, 0.25)",
            color: "#c9a84c",
          }}
        >
          Quest {proposal.quest + 1} · Round {proposal.round + 1}
        </span>
      </div>

      <div className="flex items-center gap-1.5">
        <span className="text-medieval-silver/60 font-body text-xs">
          Led by
        </span>
        <span
          className="font-display text-sm font-semibold"
          style={{ color: SEAT_COLORS[proposal.leader] }}
        >
          Player {proposal.leader}
        </span>
      </div>

      <div className="flex items-center gap-2 mt-1">
        {proposal.team.map((seat) => (
          <div
            key={seat}
            className="flex items-center justify-center w-9 h-9 rounded-full transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)]"
            style={{
              border: `2px solid ${SEAT_COLORS[seat]}`,
              background: `${SEAT_COLORS[seat]}15`,
              boxShadow: `0 0 12px 2px ${SEAT_COLORS[seat]}20`,
            }}
          >
            <span
              className="text-xs font-display font-bold"
              style={{ color: SEAT_COLORS[seat] }}
            >
              {seat}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function QuestResultBanner({
  success,
  numFails,
}: {
  success: boolean;
  numFails: number;
}) {
  return (
    <div
      className="animate-fade-up flex flex-col items-center gap-2 py-3 px-6 rounded-[1.5rem]"
      style={{
        background: success
          ? "rgba(46, 158, 91, 0.08)"
          : "rgba(196, 43, 43, 0.08)",
        border: `1px solid ${success ? "rgba(46, 158, 91, 0.2)" : "rgba(196, 43, 43, 0.2)"}`,
        boxShadow: success
          ? "0 0 40px 8px rgba(46, 158, 91, 0.1)"
          : "0 0 40px 8px rgba(196, 43, 43, 0.1)",
      }}
    >
      <span
        className={`font-display text-lg font-bold tracking-wider uppercase ${
          success ? "text-medieval-good" : "text-medieval-evil"
        }`}
      >
        {success ? "Quest Succeeded" : "Quest Failed"}
      </span>
      {!success && numFails > 0 && (
        <span className="text-medieval-evil/70 text-xs font-body">
          {numFails} fail vote{numFails !== 1 ? "s" : ""}
        </span>
      )}
    </div>
  );
}

export default function VoteOverlay({
  proposal,
  phase,
  questResult,
}: VoteOverlayProps) {
  if (!proposal && !questResult) return null;

  const votes = proposal?.votes;
  const voteEntries = votes
    ? Object.entries(votes).map(([k, v]) => ({
        player: Number(k),
        approve: v,
      }))
    : [];

  return (
    <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center z-10">
      {questResult && (
        <QuestResultBanner
          success={questResult.success}
          numFails={questResult.numFails}
        />
      )}

      {!questResult && proposal && phase === "team_selection" && (
        <TeamProposalDisplay proposal={proposal} />
      )}

      {!questResult &&
        phase === "team_voting" &&
        proposal &&
        voteEntries.length > 0 && (
          <div className="flex flex-col items-center gap-4">
            <TeamProposalDisplay proposal={proposal} />
            <div className="flex items-center gap-3 mt-2">
              {voteEntries.map((vote, i) => (
                <VoteToken
                  key={vote.player}
                  player={vote.player}
                  approve={vote.approve}
                  index={i}
                />
              ))}
            </div>
            {voteEntries.length === 5 && (
              <div className="animate-fade-up mt-1">
                <span
                  className={`font-display text-sm uppercase tracking-widest font-semibold ${
                    proposal.approved
                      ? "text-medieval-good"
                      : "text-medieval-evil/70"
                  }`}
                >
                  {proposal.approved ? "Team Approved" : "Team Rejected"}
                </span>
              </div>
            )}
          </div>
        )}
    </div>
  );
}
