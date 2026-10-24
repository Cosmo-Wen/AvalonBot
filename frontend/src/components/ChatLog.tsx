import { useEffect, useRef, useState } from "react";
import { type GameEvent, SEAT_COLORS, SEAT_NAMES } from "../types";

interface ChatLogProps {
  events: GameEvent[];
  currentSpeaker: number | null;
}

function SpeakerDot({ seat }: { seat: number }) {
  return (
    <span
      className="inline-block w-2 h-2 rounded-full mr-2 flex-shrink-0 mt-[5px]"
      style={{ backgroundColor: SEAT_COLORS[seat] }}
    />
  );
}

function UtteranceEntry({
  speaker,
  text,
  isCurrent,
}: {
  speaker: number;
  text: string;
  isCurrent: boolean;
}) {
  return (
    <div
      className={`flex items-start gap-0 py-2 px-3 rounded-lg transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)] ${
        isCurrent
          ? "border-l-2 border-medieval-gold bg-medieval-gold/[0.04]"
          : "border-l-2 border-transparent"
      }`}
    >
      <SpeakerDot seat={speaker} />
      <div className="min-w-0">
        <span
          className="font-display text-xs font-semibold mr-2"
          style={{ color: SEAT_COLORS[speaker] }}
        >
          {SEAT_NAMES[speaker]}
        </span>
        <span className="text-medieval-parchment/90 font-body text-[13px] leading-relaxed">
          {text}
        </span>
      </div>
    </div>
  );
}

function SystemEntry({ text }: { text: string }) {
  return (
    <div className="flex items-center gap-3 py-1.5 px-3">
      <div className="flex-1 h-px bg-medieval-border/40" />
      <span className="text-[10px] uppercase tracking-[0.15em] text-medieval-silver/40 font-body whitespace-nowrap">
        {text}
      </span>
      <div className="flex-1 h-px bg-medieval-border/40" />
    </div>
  );
}

function stripTtsTokens(text: string): string {
  return text
    .replace(/<\|[^|]*\|>/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function formatEvent(event: GameEvent): { speaker?: number; text: string; isSystem: boolean } {
  switch (event.type) {
    case "utterance":
      return { speaker: event.speaker, text: stripTtsTokens(event.text), isSystem: false };
    case "evil_chat":
      return { speaker: event.speaker, text: stripTtsTokens(`[Evil] ${event.text}`), isSystem: false };
    case "team_proposed":
      return {
        text: `Player ${event.leader} proposes team [${event.team.join(", ")}] for Quest ${event.quest + 1}`,
        isSystem: true,
      };
    case "team_vote_result": {
      const approveCount = Object.values(event.votes).filter(Boolean).length;
      return {
        text: event.approved
          ? `Team approved (${approveCount}–${5 - approveCount})`
          : `Team rejected (${approveCount}–${5 - approveCount})`,
        isSystem: true,
      };
    }
    case "quest_result":
      return {
        text: event.success
          ? `Quest ${event.quest + 1} succeeded`
          : `Quest ${event.quest + 1} failed — ${event.numFails} fail${event.numFails !== 1 ? "s" : ""}`,
        isSystem: true,
      };
    case "assassination":
      return {
        text: `Assassin targets Player ${event.target} — ${event.hitMerlin ? "Merlin killed!" : "Merlin survives!"}`,
        isSystem: true,
      };
    case "game_over":
      return {
        text: `Game over — ${event.winner === "good" ? "Good" : "Evil"} wins: ${event.reason}`,
        isSystem: true,
      };
    case "belief_update":
      return { text: "", isSystem: true };
    case "audio_chunk":
      return { text: "", isSystem: true };
    case "role_reveal":
      return { text: "Roles have been assigned", isSystem: true };
  }
}

export default function ChatLog({ events, currentSpeaker }: ChatLogProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [userScrolled, setUserScrolled] = useState(false);
  const prevEventCount = useRef(events.length);

  useEffect(() => {
    if (!userScrolled && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
    prevEventCount.current = events.length;
  }, [events.length, userScrolled]);

  function handleScroll() {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 40;
    setUserScrolled(!isAtBottom);
  }

  const displayEvents = events.filter(
    (e) => e.type !== "belief_update" && e.type !== "audio_chunk"
  );

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-4 pt-3 pb-2">
        <span className="rounded-full px-3 py-1 text-[10px] uppercase tracking-[0.2em] font-medium text-medieval-gold bg-medieval-gold/[0.08] border border-medieval-gold/20">
          Transcript
        </span>
        <span className="text-[10px] text-medieval-silver/40 font-mono">
          {displayEvents.length} events
        </span>
      </div>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-2 pb-3 min-h-0"
        style={{
          scrollbarWidth: "thin",
          scrollbarColor: "#2e2e3a #111118",
        }}
      >
        <div className="flex flex-col gap-0.5">
          {displayEvents.map((event, i) => {
            const formatted = formatEvent(event);
            if (!formatted.text) return null;

            if (formatted.isSystem) {
              return <SystemEntry key={`${event.seq}-${i}`} text={formatted.text} />;
            }

            return (
              <UtteranceEntry
                key={`${event.seq}-${i}`}
                speaker={formatted.speaker!}
                text={formatted.text}
                isCurrent={formatted.speaker === currentSpeaker}
              />
            );
          })}
        </div>
      </div>

      {userScrolled && (
        <button
          onClick={() => {
            setUserScrolled(false);
            scrollRef.current?.scrollTo({
              top: scrollRef.current.scrollHeight,
              behavior: "smooth",
            });
          }}
          className="mx-auto mb-2 rounded-full px-3 py-1 text-[10px] uppercase tracking-[0.1em] font-medium text-medieval-gold/70 bg-medieval-surface border border-medieval-border/50 transition-all duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] hover:text-medieval-gold hover:border-medieval-gold/30 active:scale-[0.97]"
        >
          Scroll to latest
        </button>
      )}
    </div>
  );
}
