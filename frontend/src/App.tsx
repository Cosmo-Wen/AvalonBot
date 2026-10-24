import { useCallback, useMemo, useState } from "react";
import GameTable from "./components/GameTable";
import QuestTracker from "./components/QuestTracker";
import VoteOverlay from "./components/VoteOverlay";
import ChatLog from "./components/ChatLog";
import PhaseIndicator from "./components/PhaseIndicator";
import GameControls from "./components/GameControls";
import { BeliefPanel } from "./components/BeliefPanel";
import { useGameSocket } from "./hooks/useGameSocket";
import { useAudio } from "./hooks/useAudio";
import { useLiveKit } from "./hooks/useLiveKit";
import { SEAT_NAMES } from "./types";

export default function App() {
  const [showRoles, setShowRoles] = useState(false);
  const [speed, setSpeedLocal] = useState(1);
  const [isPlaying, setIsPlaying] = useState(false);

  const { playAudioChunk, audioLevels, isSpeaking, setMuted, isMuted } = useAudio();
  const livekit = useLiveKit();

  const onAudioChunk = useCallback(
    (seat: number, data: string) => {
      playAudioChunk(seat, data);
    },
    [playAudioChunk]
  );

  const {
    gameState,
    isConnected,
    startGame,
    pause,
    resume,
    step,
    setSpeed,
    availableGames,
  } = useGameSocket("/ws/game", onAudioChunk);

  const players = useMemo(
    () =>
      gameState.players.map((p) => ({
        ...p,
        isSpeaking: isSpeaking[p.seat] ?? p.isSpeaking,
        audioLevel: audioLevels[p.seat] ?? p.audioLevel,
      })),
    [gameState.players, isSpeaking, audioLevels]
  );

  const currentSpeaker = useMemo(() => {
    const speaking = players.find((p) => p.isSpeaking);
    return speaking?.seat ?? null;
  }, [players]);

  const phaseDetails = useMemo(() => {
    const { phase, leader, turn, roundNum, currentProposal } = gameState;
    switch (phase) {
      case "waiting":
        return isConnected
          ? "Connect to a game or load a replay"
          : "Connecting to server…";
      case "team_selection":
        return `Quest ${turn + 1} · Round ${roundNum + 1} · ${SEAT_NAMES[leader]} is the leader`;
      case "team_voting":
        return currentProposal
          ? `Voting on [${currentProposal.team.join(", ")}] proposed by ${SEAT_NAMES[currentProposal.leader]}`
          : "Votes in progress";
      case "quest_voting":
        return `Quest ${turn + 1} — team members casting quest votes`;
      case "assassination":
        return "Good won 3 quests — the Assassin hunts for Merlin";
      case "game_over": {
        const lastEvent = gameState.events[gameState.events.length - 1];
        if (lastEvent?.type === "game_over") {
          return `${lastEvent.winner === "good" ? "Good" : "Evil"} wins — ${lastEvent.reason}`;
        }
        return "Game complete";
      }
      default:
        return "";
    }
  }, [gameState, isConnected]);

  const lastQuestResult = useMemo(() => {
    const completed = gameState.quests.filter((q) => q !== null);
    if (completed.length === 0) return null;
    const last = completed[completed.length - 1]!;
    return { success: last.success, numFails: last.numFails };
  }, [gameState.quests]);

  const winner = useMemo(() => {
    const lastEvent = gameState.events[gameState.events.length - 1];
    if (lastEvent?.type === "game_over") return lastEvent.winner;
    return null;
  }, [gameState.events]);

  const handlePlayPause = useCallback(() => {
    if (isPlaying) {
      pause();
      setIsPlaying(false);
    } else {
      resume();
      setIsPlaying(true);
    }
  }, [isPlaying, pause, resume]);

  const handleSpeedChange = useCallback(
    (s: number) => {
      setSpeedLocal(s);
      setSpeed(s);
    },
    [setSpeed]
  );

  const handleNewGame = useCallback(() => {
    if (livekit.available && !livekit.connected) {
      livekit.connect();
    }
    startGame("live");
    setIsPlaying(true);
  }, [startGame, livekit]);

  const handleLoadReplay = useCallback(
    (file: string) => {
      startGame("replay", file);
      setIsPlaying(true);
    },
    [startGame]
  );

  const progress = useMemo(() => {
    const totalEvents = gameState.events.length;
    return {
      current: totalEvents,
      total: totalEvents,
      quest: gameState.turn + 1,
      round: gameState.roundNum + 1,
    };
  }, [gameState.events.length, gameState.turn, gameState.roundNum]);

  return (
    <div
      className="min-h-[100dvh] flex flex-col"
      style={{
        background:
          "radial-gradient(ellipse at 50% 30%, rgba(30, 25, 50, 0.4) 0%, #0a0a0f 60%)",
      }}
    >
      {/* Phase banner */}
      <div className="shrink-0 animate-fade-up">
        <PhaseIndicator
          phase={gameState.phase}
          details={phaseDetails}
          winner={winner}
        />
      </div>

      {/* Main content grid */}
      <div className="flex-1 w-full max-w-[1440px] mx-auto px-4 md:px-6 py-4 grid grid-cols-1 md:grid-cols-[280px_1fr_320px] gap-4 md:gap-5 min-h-0">
        {/* Left column — Quest Tracker + Belief Graph */}
        <div className="flex flex-col gap-4 min-h-0 order-2 md:order-1">
          <div className="animate-fade-up" style={{ animationDelay: "100ms" }}>
            <QuestTracker
              quests={gameState.quests}
              currentQuest={gameState.turn + 1}
            />
          </div>

          <div className="animate-fade-up" style={{ animationDelay: "200ms" }}>
            <BeliefPanel
              beliefs={gameState.beliefs}
              quests={gameState.quests}
            />
          </div>

          {/* Audio / reveal controls */}
          <div className="animate-fade-up flex gap-2" style={{ animationDelay: "300ms" }}>
            <button
              onClick={() => setMuted(!isMuted)}
              className="flex-1 rounded-xl border border-medieval-border bg-medieval-darker px-3 py-2 text-xs font-body text-medieval-parchment-dim transition-all duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] hover:border-medieval-gold/30 hover:text-medieval-gold active:scale-[0.97]"
            >
              {isMuted ? "Unmute Audio" : "Mute Audio"}
            </button>
            <button
              onClick={() => setShowRoles(!showRoles)}
              className="flex-1 rounded-xl border border-medieval-border bg-medieval-darker px-3 py-2 text-xs font-body text-medieval-parchment-dim transition-all duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] hover:border-medieval-gold/30 hover:text-medieval-gold active:scale-[0.97]"
            >
              {showRoles ? "Hide Roles" : "Reveal Roles"}
            </button>
          </div>
        </div>

        {/* Center — Game Table + Vote Overlay */}
        <div className="flex flex-col items-center justify-center min-h-0 order-1 md:order-2">
          <div
            className="w-full max-w-[640px] animate-fade-up relative"
            style={{ animationDelay: "50ms" }}
          >
            <GameTable
              players={players}
              leader={gameState.leader}
              proposal={gameState.currentProposal}
              showRoles={showRoles}
              seatVideos={livekit.connected ? livekit.seatVideos : undefined}
            />
            <div className="absolute inset-0 pointer-events-none flex items-center justify-center">
              <VoteOverlay
                proposal={gameState.currentProposal}
                phase={gameState.phase}
                questResult={lastQuestResult}
              />
            </div>
          </div>
        </div>

        {/* Right column — Chat Log */}
        <div
          className="min-h-0 order-3 rounded-[1.25rem] border border-medieval-border bg-medieval-darker overflow-hidden flex flex-col animate-fade-up"
          style={{
            animationDelay: "150ms",
            maxHeight: "calc(100dvh - 180px)",
          }}
        >
          <ChatLog events={gameState.events} currentSpeaker={currentSpeaker} />
        </div>
      </div>

      {/* Bottom controls */}
      <div className="shrink-0 animate-fade-up" style={{ animationDelay: "250ms" }}>
        <GameControls
          isPlaying={isPlaying}
          speed={speed}
          onPlayPause={handlePlayPause}
          onStep={step}
          onSpeedChange={handleSpeedChange}
          onNewGame={handleNewGame}
          onLoadReplay={handleLoadReplay}
          progress={progress}
          availableReplays={availableGames}
        />
      </div>
    </div>
  );
}
