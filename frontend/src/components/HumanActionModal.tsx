import { useState, useRef, useEffect } from "react";
import { type HumanActionPrompt, SEAT_COLORS, SEAT_NAMES, seatName } from "../types";

interface HumanActionModalProps {
  prompt: HumanActionPrompt;
  onRespond: (action: string, data: Record<string, unknown>) => void;
}

export default function HumanActionModal({ prompt, onRespond }: HumanActionModalProps) {
  const { action, turn = 0, teamSize = 2, leader = 0, team = [], canFail = false, candidates = [] } = prompt;

  // State for team proposal selection
  const [selectedTeam, setSelectedTeam] = useState<number[]>([]);

  // State for discussion utterance
  const [discussionText, setDiscussionText] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [micStatus, setMicStatus] = useState<string | null>(null);
  const speakVoice = false;
  const recognitionRef = useRef<any>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);

  // Clean up any active audio stream / recognition when unmounting
  useEffect(() => {
    return () => {
      if (recognitionRef.current) {
        try {
          recognitionRef.current.abort();
        } catch {}
      }
      if (mediaStreamRef.current) {
        try {
          mediaStreamRef.current.getTracks().forEach((t) => t.stop());
        } catch {}
      }
    };
  }, []);

  const startPushToTalk = async () => {
    setMicStatus(null);
    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

    // 1. Explicitly request microphone stream so browser prompts user
    try {
      if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaStreamRef.current = stream;
      }
    } catch (err: any) {
      console.warn("Microphone permission error:", err);
      setMicStatus("Microphone permission denied. Please allow microphone access in your browser bar.");
      return;
    }

    // 2. Start Speech Recognition
    if (SpeechRecognition) {
      try {
        if (recognitionRef.current) {
          try {
            recognitionRef.current.abort();
          } catch {}
        }
        const recognition = new SpeechRecognition();
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.lang = "en-US";

        recognition.onresult = (event: any) => {
          let text = "";
          for (let i = 0; i < event.results.length; i++) {
            text += event.results[i][0].transcript + " ";
          }
          if (text.trim()) {
            setDiscussionText(text.trim());
          }
        };

        recognition.onerror = (event: any) => {
          console.warn("Speech recognition error:", event.error);
          if (event.error === "not-allowed") {
            setMicStatus("Microphone blocked. Please click the lock/camera icon in your address bar to allow mic.");
          } else if (event.error === "network") {
            setMicStatus("Browser speech service network issue. You can still type or pick suggestions below.");
          }
        };

        recognition.onend = () => {
          // Keep isRecording state managed by user release
        };

        recognition.start();
        recognitionRef.current = recognition;
        setIsRecording(true);
      } catch (err: any) {
        console.warn("Speech recognition start failed:", err);
        setMicStatus("Could not start speech recognition. You can type or use suggestions below.");
        setIsRecording(true);
      }
    } else {
      setMicStatus("Web Speech API not supported in this browser. Please use Chrome/Edge or type below.");
      setIsRecording(true);
    }
  };

  const stopPushToTalk = () => {
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch {}
      recognitionRef.current = null;
    }
    if (mediaStreamRef.current) {
      try {
        mediaStreamRef.current.getTracks().forEach((t) => t.stop());
      } catch {}
      mediaStreamRef.current = null;
    }
    setIsRecording(false);
  };

  const togglePushToTalk = () => {
    if (isRecording) {
      stopPushToTalk();
    } else {
      void startPushToTalk();
    }
  };

  const toggleSeat = (seat: number) => {
    if (selectedTeam.includes(seat)) {
      setSelectedTeam(selectedTeam.filter((s) => s !== seat));
    } else {
      if (selectedTeam.length < teamSize) {
        setSelectedTeam([...selectedTeam, seat]);
      }
    }
  };

  const handlePropose = () => {
    if (selectedTeam.length === teamSize) {
      onRespond("propose_team", { team: selectedTeam });
    }
  };

  const handleVote = (approved: boolean) => {
    onRespond("vote_on_team", { vote: approved });
  };

  const handleQuestCard = (pass: boolean) => {
    onRespond("vote_on_quest", { vote: pass });
  };

  const handleDiscussionSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    stopPushToTalk();
    const finalTxt =
      discussionText.trim() ||
      "I am a loyal servant of Arthur and want what is best for the realm.";
    onRespond("discussion", {
      text: finalTxt,
      speak_audio: speakVoice,
    });
  };

  const handleAssassinate = (target: number) => {
    onRespond("assassinate", { target });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-4 backdrop-blur-md animate-fade-in">
      <div
        className="relative w-full max-w-lg rounded-3xl border border-medieval-gold/40 bg-medieval-darker/95 p-6 shadow-2xl transition-all duration-300"
        style={{
          boxShadow: "0 0 50px rgba(201, 168, 76, 0.2), inset 0 0 20px rgba(0, 0, 0, 0.8)",
        }}
      >
        {/* Decorative corner accents */}
        <div className="absolute -top-1 -left-1 h-4 w-4 border-t-2 border-l-2 border-medieval-gold" />
        <div className="absolute -top-1 -right-1 h-4 w-4 border-t-2 border-r-2 border-medieval-gold" />
        <div className="absolute -bottom-1 -left-1 h-4 w-4 border-b-2 border-l-2 border-medieval-gold" />
        <div className="absolute -bottom-1 -right-1 h-4 w-4 border-b-2 border-r-2 border-medieval-gold" />

        {/* ── 1. PROPOSE TEAM ─────────────────────────────────── */}
        {action === "propose_team" && (
          <div className="flex flex-col items-center gap-4 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-medieval-gold/15 text-2xl border border-medieval-gold/30">
              👑
            </div>
            <div>
              <h2 className="font-display text-lg font-bold tracking-wider text-medieval-gold">
                YOU ARE THE LEADER
              </h2>
              <p className="mt-1 font-body text-xs text-medieval-parchment-dim">
                Quest {turn + 1} · Select exactly <span className="font-bold text-medieval-gold">{teamSize} knights</span> to embark on this quest.
              </p>
            </div>

            <div className="grid w-full grid-cols-5 gap-2 my-2">
              {SEAT_NAMES.map((name, seat) => {
                const isSelected = selectedTeam.includes(seat);
                const color = SEAT_COLORS[seat];
                return (
                  <button
                    key={seat}
                    type="button"
                    onClick={() => toggleSeat(seat)}
                    className={`flex flex-col items-center justify-center rounded-xl p-2.5 transition-all duration-200 border ${
                      isSelected
                        ? "border-medieval-gold bg-medieval-gold/20 scale-105 shadow-md shadow-medieval-gold/20"
                        : "border-medieval-border bg-medieval-surface/70 hover:border-medieval-gold/30 hover:bg-medieval-surface"
                    }`}
                  >
                    <div
                      className="flex h-9 w-9 items-center justify-center rounded-full font-display text-sm font-bold border"
                      style={{
                        borderColor: color,
                        color: color,
                        backgroundColor: `${color}18`,
                      }}
                    >
                      {name[0]}
                    </div>
                    <span className="mt-1 font-display text-[11px] text-medieval-parchment">{name}</span>
                    <span className="font-mono text-[9px] text-medieval-silver/60">P{seat}</span>
                    {isSelected && (
                      <span className="mt-1 text-[10px] text-medieval-gold font-bold">✓ Selected</span>
                    )}
                  </button>
                );
              })}
            </div>

            <div className="flex items-center justify-between w-full mt-2 font-body text-xs text-medieval-silver/80">
              <span>
                Selected: <strong className="text-medieval-gold">{selectedTeam.length}</strong> / {teamSize}
              </span>
              <button
                type="button"
                onClick={handlePropose}
                disabled={selectedTeam.length !== teamSize}
                className="rounded-full bg-medieval-gold px-6 py-2 font-display text-xs font-bold text-black transition-all duration-200 hover:bg-[#e8c95a] disabled:cursor-not-allowed disabled:opacity-30 active:scale-95 shadow-lg shadow-medieval-gold/20"
              >
                Confirm Team Proposal
              </button>
            </div>
          </div>
        )}

        {/* ── 2. VOTE ON TEAM ─────────────────────────────────── */}
        {action === "vote_on_team" && (
          <div className="flex flex-col items-center gap-4 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-medieval-gold/15 text-2xl border border-medieval-gold/30">
              🗳️
            </div>
            <div>
              <h2 className="font-display text-lg font-bold tracking-wider text-medieval-gold">
                COUNCIL VOTE
              </h2>
              <p className="mt-1 font-body text-xs text-medieval-parchment-dim">
                Leader <strong style={{ color: SEAT_COLORS[leader] }}>{seatName(leader)}</strong> has proposed a team for Quest {turn + 1}.
              </p>
            </div>

            <div className="my-2 rounded-2xl border border-medieval-border/60 bg-medieval-surface/80 p-3 w-full">
              <span className="font-display text-[10px] uppercase tracking-widest text-medieval-gold-dim block mb-1">
                Proposed Knights
              </span>
              <div className="flex flex-wrap items-center justify-center gap-2">
                {team.map((seat) => (
                  <span
                    key={seat}
                    className="rounded-full border px-3 py-1 font-display text-xs font-semibold"
                    style={{
                      borderColor: SEAT_COLORS[seat],
                      color: SEAT_COLORS[seat],
                      background: `${SEAT_COLORS[seat]}1a`,
                    }}
                  >
                    {seatName(seat)} (P{seat})
                  </span>
                ))}
              </div>
            </div>

            <p className="font-body text-xs text-medieval-parchment/90">
              Do you approve this quest proposal?
            </p>

            <div className="grid grid-cols-2 gap-3 w-full mt-1">
              <button
                type="button"
                onClick={() => handleVote(true)}
                className="flex items-center justify-center gap-2 rounded-2xl border border-medieval-good/60 bg-medieval-good/20 py-3 font-display text-sm font-bold text-medieval-good hover:bg-medieval-good/30 active:scale-95 transition-all shadow-lg shadow-medieval-good/10"
              >
                <span>✅</span> Approve (Yes)
              </button>
              <button
                type="button"
                onClick={() => handleVote(false)}
                className="flex items-center justify-center gap-2 rounded-2xl border border-medieval-crimson-bright/60 bg-medieval-crimson-bright/20 py-3 font-display text-sm font-bold text-[#f08a8a] hover:bg-medieval-crimson-bright/30 active:scale-95 transition-all shadow-lg shadow-medieval-crimson-bright/10"
              >
                <span>❌</span> Reject (No)
              </button>
            </div>
          </div>
        )}

        {/* ── 3. SECRET QUEST VOTE (Pass / Fail) ──────────────── */}
        {action === "vote_on_quest" && (
          <div className="flex flex-col items-center gap-4 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-medieval-gold/15 text-2xl border border-medieval-gold/30">
              ⚔️
            </div>
            <div>
              <h2 className="font-display text-lg font-bold tracking-wider text-medieval-gold">
                SECRET QUEST CARD
              </h2>
              <p className="mt-1 font-body text-xs text-medieval-silver/80">
                You are on the quest team for <strong className="text-medieval-gold">Quest {turn + 1}</strong>.
              </p>
            </div>

            {!canFail ? (
              // Good Player: Must Pass
              <div className="flex flex-col items-center gap-3 w-full">
                <div className="rounded-2xl border border-medieval-good/40 bg-medieval-good/10 p-4 w-full text-center">
                  <span className="text-3xl block mb-1">🛡️</span>
                  <p className="font-display text-sm font-bold text-medieval-good">
                    Loyal Servant of Arthur
                  </p>
                  <p className="font-body text-xs text-medieval-parchment-dim mt-1">
                    Good players cannot fail quests. Your duty to Arthur is to cast a SUCCESS card.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => handleQuestCard(true)}
                  className="w-full rounded-2xl bg-medieval-good py-3.5 font-display text-sm font-bold text-black hover:bg-[#5ae092] active:scale-95 transition-all shadow-lg shadow-medieval-good/30"
                >
                  Cast Pass Card (Success)
                </button>
              </div>
            ) : (
              // Evil Player: Secret choice between Pass and Fail
              <div className="flex flex-col items-center gap-3 w-full">
                <div className="rounded-xl border border-medieval-crimson-bright/30 bg-[#240c0c]/80 p-2.5 w-full text-center">
                  <span className="font-mono text-[11px] text-[#f08a8a] font-semibold">
                    🤫 100% Secret Choice · No one else can see your card
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-3 w-full">
                  <button
                    type="button"
                    onClick={() => handleQuestCard(true)}
                    className="flex flex-col items-center justify-center rounded-2xl border border-medieval-good/50 bg-medieval-good/15 p-4 transition-all hover:bg-medieval-good/25 hover:scale-[1.02] active:scale-95 group text-center"
                  >
                    <span className="text-3xl mb-2">🛡️</span>
                    <span className="font-display text-sm font-bold text-medieval-good">PASS</span>
                    <span className="font-body text-[10px] text-medieval-silver/70 mt-1">
                      Support quest (blend in with Good)
                    </span>
                  </button>

                  <button
                    type="button"
                    onClick={() => handleQuestCard(false)}
                    className="flex flex-col items-center justify-center rounded-2xl border border-medieval-crimson-bright/50 bg-medieval-crimson-bright/15 p-4 transition-all hover:bg-medieval-crimson-bright/25 hover:scale-[1.02] active:scale-95 group text-center"
                  >
                    <span className="text-3xl mb-2">🗡️</span>
                    <span className="font-display text-sm font-bold text-[#f08a8a]">FAIL</span>
                    <span className="font-body text-[10px] text-medieval-silver/70 mt-1">
                      Sabotage quest (strike for Evil)
                    </span>
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── 4. DISCUSSION ───────────────────────────────────── */}
        {action === "discussion" && (
          <form onSubmit={handleDiscussionSubmit} className="flex flex-col items-center gap-3 text-center w-full">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-medieval-gold/15 text-2xl border border-medieval-gold/30">
              💬
            </div>
            <div>
              <h2 className="font-display text-lg font-bold tracking-wider text-medieval-gold">
                YOUR TURN TO SPEAK
              </h2>
              <p className="mt-1 font-body text-xs text-medieval-parchment-dim">
                Address the Round Table as <span className="font-bold text-medieval-gold">Atlas (Player 0)</span>.
              </p>
            </div>

            {/* Push-to-Talk Microphone Button */}
            <div className="w-full">
              <button
                type="button"
                onClick={togglePushToTalk}
                className={`flex items-center justify-center gap-3 w-full rounded-2xl py-3 px-4 font-display text-xs font-bold transition-all duration-200 border select-none cursor-pointer ${
                  isRecording
                    ? "border-medieval-crimson-bright bg-medieval-crimson-bright/30 text-white shadow-xl shadow-medieval-crimson-bright/40 scale-[1.01] ring-2 ring-medieval-crimson-bright animate-pulse"
                    : "border-medieval-gold/50 bg-medieval-gold/15 text-medieval-gold hover:bg-medieval-gold/25 hover:border-medieval-gold active:scale-98"
                }`}
              >
                <span className="text-xl">{isRecording ? "🔴" : "🎙️"}</span>
                <div className="flex flex-col text-left">
                  <span className="text-xs uppercase tracking-wider font-bold">
                    {isRecording ? "Listening... (Click to Finish Speaking)" : "Click to Speak with Microphone (STT)"}
                  </span>
                  <span className="text-[10px] font-normal text-medieval-silver/80">
                    {isRecording ? "Transcribing live... click when done speaking" : "Click to start speech transcription, speak, then click submit"}
                  </span>
                </div>
              </button>

              {micStatus && (
                <div className="mt-2 rounded-xl border border-medieval-crimson-bright/40 bg-medieval-crimson-bright/15 p-2 text-center font-body text-[11px] text-[#f08a8a]">
                  ⚠️ {micStatus}
                </div>
              )}
            </div>

            {/* Statement Input Box */}
            <div className="w-full text-left">
              <label className="font-display text-[10px] tracking-wider text-medieval-silver/60 uppercase block mb-1">
                Your Statement:
              </label>
              <textarea
                rows={2}
                value={discussionText}
                onChange={(e) => setDiscussionText(e.target.value)}
                placeholder="Type or use Push-to-Talk to compose your statement..."
                autoFocus
                className="w-full rounded-xl border border-medieval-border bg-medieval-surface px-4 py-2.5 font-body text-xs text-medieval-parchment placeholder-medieval-silver/40 focus:border-medieval-gold focus:outline-none resize-none"
              />
            </div>

            {/* Quick Suggestion Options (CLICK ONLY FILLS, DOES NOT AUTO-SUBMIT) */}
            <div className="w-full">
              <span className="font-display text-[10px] tracking-wider text-medieval-silver/60 uppercase block mb-1.5 text-left">
                Suggested Statements (Click to fill text box):
              </span>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 text-left">
                {[
                  "I am a loyal servant of Arthur and want what is best for the realm.",
                  "I trust this team proposal and believe we should approve it.",
                  "I strongly suspect there is an agent of Mordred among us.",
                  "We must be extremely cautious and reject this expedition.",
                ].map((phrase) => {
                  const isSelected = discussionText === phrase;
                  return (
                    <button
                      key={phrase}
                      type="button"
                      onClick={() => setDiscussionText(phrase)}
                      className={`rounded-xl border p-2.5 text-left font-body text-[11px] leading-snug transition-all cursor-pointer ${
                        isSelected
                          ? "border-medieval-gold bg-medieval-gold/20 text-medieval-gold ring-1 ring-medieval-gold"
                          : "border-medieval-border/70 bg-medieval-surface/60 text-medieval-silver/90 hover:border-medieval-gold/40 hover:bg-medieval-surface"
                      }`}
                    >
                      "{phrase}"
                      {isSelected && (
                        <span className="block mt-1 font-display text-[10px] text-medieval-gold font-bold">
                          ✓ Selected
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>


            {/* EXPLICIT SUBMIT BUTTON BEFORE PROCEEDING */}
            <div className="w-full pt-1 flex flex-col gap-1.5">
              <button
                type="submit"
                className="w-full rounded-2xl py-3.5 font-display text-xs font-bold tracking-wider transition-all duration-200 shadow-lg bg-medieval-gold text-black hover:bg-[#e8c95a] active:scale-98 shadow-medieval-gold/25 cursor-pointer"
              >
                🚀 SUBMIT STATEMENT & PROCEED
              </button>
              <p className="font-body text-[10px] text-medieval-silver/60 text-center">
                Review your statement above. Clicking submit confirms your words and moves to the next player.
              </p>
            </div>
          </form>
        )}

        {/* ── 5. ASSASSINATION ────────────────────────────────── */}
        {action === "assassinate" && (
          <div className="flex flex-col items-center gap-4 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-medieval-crimson-bright/20 text-2xl border border-medieval-crimson-bright/40">
              🎯
            </div>
            <div>
              <h2 className="font-display text-lg font-bold tracking-wider text-[#f08a8a]">
                ASSASSIN'S STRIKE
              </h2>
              <p className="mt-1 font-body text-xs text-medieval-parchment-dim">
                Good won 3 quests! Identify Merlin to steal victory for Evil:
              </p>
            </div>

            <div className="grid grid-cols-2 gap-2.5 w-full my-1">
              {candidates.map((seat) => (
                <button
                  key={seat}
                  type="button"
                  onClick={() => handleAssassinate(seat)}
                  className="flex items-center gap-3 rounded-xl border border-medieval-border bg-medieval-surface/80 p-3 hover:border-[#f08a8a] hover:bg-[#2a0e0e] active:scale-95 transition-all"
                >
                  <div
                    className="flex h-8 w-8 items-center justify-center rounded-full font-display text-xs font-bold border"
                    style={{
                      borderColor: SEAT_COLORS[seat],
                      color: SEAT_COLORS[seat],
                      backgroundColor: `${SEAT_COLORS[seat]}18`,
                    }}
                  >
                    {seatName(seat)[0]}
                  </div>
                  <div className="text-left">
                    <span className="font-display text-xs font-bold text-medieval-parchment block">
                      {seatName(seat)}
                    </span>
                    <span className="font-mono text-[9px] text-medieval-silver/60">
                      Player {seat}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
