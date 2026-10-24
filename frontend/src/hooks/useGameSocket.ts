import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import type {
  GameState,
  GamePhase,
  Player,
  PlayerRole,
  PlayerSide,
  QuestResult,
  TeamProposal,
  GameEvent,
  BeliefSnapshot,
} from "../types";
import { SEAT_NAMES, QUEST_SIZES } from "../types";

const INITIAL_PLAYERS: Player[] = Array.from({ length: 5 }, (_, i) => ({
  seat: i,
  name: SEAT_NAMES[i],
  isSpeaking: false,
  audioLevel: 0,
}));

const INITIAL_STATE: GameState = {
  phase: "waiting",
  turn: 0,
  roundNum: 0,
  leader: 0,
  players: INITIAL_PLAYERS,
  quests: [null, null, null, null, null],
  currentProposal: null,
  events: [],
  beliefs: {},
  rolesRevealed: false,
};

type Action =
  | { type: "RESET" }
  | { type: "GAME_START"; data: Record<string, unknown> }
  | { type: "PHASE_CHANGE"; phase: GamePhase }
  | { type: "UTTERANCE"; event: GameEvent }
  | { type: "EVIL_CHAT"; event: GameEvent }
  | { type: "TEAM_PROPOSED"; data: Record<string, unknown>; seq: number }
  | { type: "TEAM_VOTE_RESULT"; data: Record<string, unknown>; seq: number }
  | { type: "QUEST_RESULT"; data: Record<string, unknown>; seq: number }
  | { type: "BELIEF_UPDATE"; data: Record<string, unknown>; seq: number }
  | { type: "ASSASSINATION"; data: Record<string, unknown>; seq: number }
  | { type: "GAME_OVER"; data: Record<string, unknown>; seq: number }
  | { type: "ROLE_REVEAL"; data: Record<string, unknown>; seq: number }
  | { type: "SET_SPEAKING"; seat: number; speaking: boolean }
  | { type: "SET_AUDIO_LEVEL"; seat: number; level: number };

function gameReducer(state: GameState, action: Action): GameState {
  switch (action.type) {
    case "RESET":
      return { ...INITIAL_STATE, players: INITIAL_PLAYERS.map((p) => ({ ...p })) };

    case "GAME_START": {
      const d = action.data;
      const leader = (d.leader as number) ?? 0;
      return {
        ...INITIAL_STATE,
        phase: "team_selection",
        leader,
        players: INITIAL_PLAYERS.map((p) => ({ ...p })),
        events: [],
        quests: [null, null, null, null, null],
        beliefs: {},
      };
    }

    case "ROLE_REVEAL": {
      const d = action.data;
      const roles = d.roles as Record<string, PlayerRole>;
      const sides = d.sides as Record<string, PlayerSide>;
      const players = state.players.map((p) => ({
        ...p,
        role: roles[String(p.seat)] ?? p.role,
        side: sides[String(p.seat)] ?? p.side,
      }));
      return { ...state, players, rolesRevealed: true };
    }

    case "PHASE_CHANGE":
      return { ...state, phase: action.phase };

    case "UTTERANCE": {
      const ev = action.event;
      const speaker = ev.type === "utterance" ? ev.speaker : -1;
      return {
        ...state,
        players: state.players.map((p) => ({
          ...p,
          isSpeaking: p.seat === speaker,
        })),
        events: [...state.events, ev],
      };
    }

    case "EVIL_CHAT":
      return { ...state, events: [...state.events, action.event] };

    case "TEAM_PROPOSED": {
      const d = action.data;
      const quest = d.turn !== undefined ? (d.turn as number) + 1 : state.turn + 1;
      const round = (d.round_num as number) ?? state.roundNum;
      const proposal: TeamProposal = {
        leader: d.leader as number,
        team: d.team as number[],
        quest,
        round,
      };
      const event: GameEvent = {
        type: "team_proposed",
        leader: proposal.leader,
        team: proposal.team,
        quest,
        round,
        seq: action.seq,
      };
      return {
        ...state,
        phase: "team_voting",
        currentProposal: proposal,
        turn: quest - 1,
        roundNum: round,
        events: [...state.events, event],
      };
    }

    case "TEAM_VOTE_RESULT": {
      const d = action.data;
      const rawVotes = d.votes as Record<string, boolean>;
      const approved = d.approved as boolean;
      const votes: Record<number, boolean> = {};
      for (const [seat, val] of Object.entries(rawVotes)) {
        votes[Number(seat)] = val;
      }
      const quest = (d.turn as number | undefined) !== undefined
        ? (d.turn as number) + 1
        : state.currentProposal?.quest ?? state.turn + 1;
      const round = (d.round_num as number) ?? state.roundNum;
      const updatedProposal: TeamProposal | null = state.currentProposal
        ? { ...state.currentProposal, votes, approved }
        : null;
      const event: GameEvent = {
        type: "team_vote_result",
        votes,
        approved,
        quest,
        round,
        seq: action.seq,
      };
      return {
        ...state,
        phase: approved ? "quest_voting" : "team_selection",
        currentProposal: updatedProposal,
        roundNum: approved ? round : round + 1,
        leader: approved ? state.leader : (state.leader + 1) % 5,
        players: state.players.map((p) => ({ ...p, isSpeaking: false })),
        events: [...state.events, event],
      };
    }

    case "QUEST_RESULT": {
      const d = action.data;
      const questIdx = d.turn !== undefined ? (d.turn as number) : state.turn;
      const success = d.success as boolean;
      const numFails = (d.num_fails as number) ?? 0;
      const team = (d.team as number[]) ?? state.currentProposal?.team ?? [];
      const result: QuestResult = {
        quest: questIdx + 1,
        team,
        success,
        numFails,
      };
      const quests = [...state.quests];
      quests[questIdx] = result;
      const goodScore = quests.filter((q) => q?.success === true).length;
      const evilScore = quests.filter((q) => q !== null && !q.success).length;
      const event: GameEvent = {
        type: "quest_result",
        quest: questIdx + 1,
        team,
        success,
        numFails,
        seq: action.seq,
      };
      const nextPhase: GamePhase =
        goodScore >= 3
          ? "assassination"
          : evilScore >= 3
            ? "game_over"
            : "team_selection";
      return {
        ...state,
        phase: nextPhase,
        quests,
        turn: questIdx + 1,
        roundNum: 0,
        leader: (state.leader + 1) % 5,
        currentProposal: null,
        events: [...state.events, event],
      };
    }

    case "BELIEF_UPDATE": {
      const d = action.data;
      const snap: BeliefSnapshot = {
        seq: action.seq,
        player: d.player as number,
        pEvil: d.p_evil as Record<number, number>,
      };
      const player = snap.player;
      const existing = state.beliefs[player] ?? [];
      return {
        ...state,
        beliefs: { ...state.beliefs, [player]: [...existing, snap] },
      };
    }

    case "ASSASSINATION": {
      const d = action.data;
      const event: GameEvent = {
        type: "assassination",
        assassin: d.assassin as number,
        target: d.target as number,
        hitMerlin: d.hit_merlin as boolean,
        seq: action.seq,
      };
      return { ...state, events: [...state.events, event] };
    }

    case "GAME_OVER": {
      const d = action.data;
      const event: GameEvent = {
        type: "game_over",
        winner: (d.winner as string) === "Good" ? "good" : "evil",
        reason: (d.reason as string) ?? "",
        seq: action.seq,
      };
      return {
        ...state,
        phase: "game_over",
        players: state.players.map((p) => ({ ...p, isSpeaking: false })),
        events: [...state.events, event],
      };
    }

    case "SET_SPEAKING":
      return {
        ...state,
        players: state.players.map((p) =>
          p.seat === action.seat ? { ...p, isSpeaking: action.speaking } : p
        ),
      };

    case "SET_AUDIO_LEVEL":
      return {
        ...state,
        players: state.players.map((p) =>
          p.seat === action.seat ? { ...p, audioLevel: action.level } : p
        ),
      };

    default:
      return state;
  }
}

export type GameAction = Action;

interface UseGameSocketReturn {
  gameState: GameState;
  isConnected: boolean;
  startGame: (mode: "live" | "replay", replayFile?: string) => void;
  pause: () => void;
  resume: () => void;
  step: () => void;
  setSpeed: (speed: number) => void;
  availableGames: string[];
  dispatch: React.Dispatch<Action>;
}

export function useGameSocket(
  wsUrl = "/ws/game",
  onAudioChunk?: (seat: number, data: string) => void
): UseGameSocketReturn {
  const [state, dispatch] = useReducer(gameReducer, INITIAL_STATE);
  const [isConnected, setIsConnected] = useState(false);
  const [availableGames, setAvailableGames] = useState<string[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectDelay = useRef(1000);

  const send = useCallback((msg: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = wsUrl.startsWith("/")
      ? `${protocol}//${window.location.host}${wsUrl}`
      : wsUrl;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
      reconnectDelay.current = 1000;
      send({ type: "list_games" });
    };

    ws.onmessage = (event) => {
      let msg: { type: string; data?: Record<string, unknown>; seq?: number };
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }

      const d = msg.data ?? {};
      const seq = msg.seq ?? 0;

      switch (msg.type) {
        case "game_list":
          setAvailableGames((d.games as string[]) ?? []);
          break;
        case "game_start":
          dispatch({ type: "GAME_START", data: d });
          break;
        case "role_reveal":
          dispatch({ type: "ROLE_REVEAL", data: d, seq });
          break;
        case "phase_change":
          dispatch({ type: "PHASE_CHANGE", phase: d.phase as GamePhase });
          break;
        case "utterance":
          dispatch({
            type: "UTTERANCE",
            event: {
              type: "utterance",
              seq,
              speaker: d.speaker as number,
              text: d.text as string,
            },
          });
          break;
        case "evil_chat":
          dispatch({
            type: "EVIL_CHAT",
            event: {
              type: "evil_chat",
              seq,
              speaker: d.speaker as number,
              text: d.text as string,
            },
          });
          break;
        case "team_proposed":
          dispatch({ type: "TEAM_PROPOSED", data: d, seq });
          break;
        case "team_vote_result":
          dispatch({ type: "TEAM_VOTE_RESULT", data: d, seq });
          break;
        case "quest_result":
          dispatch({ type: "QUEST_RESULT", data: d, seq });
          break;
        case "belief_update":
          dispatch({ type: "BELIEF_UPDATE", data: d, seq });
          break;
        case "assassination":
          dispatch({ type: "ASSASSINATION", data: d, seq });
          break;
        case "game_over":
          dispatch({ type: "GAME_OVER", data: d, seq });
          break;
        case "audio_chunk":
          if (onAudioChunk) {
            onAudioChunk(d.speaker as number, d.audio as string);
          }
          break;
        case "speaking_start":
          dispatch({ type: "SET_SPEAKING", seat: d.speaker as number, speaking: true });
          break;
        case "speaking_stop":
          dispatch({ type: "SET_SPEAKING", seat: d.speaker as number, speaking: false });
          break;
        default:
          break;
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      wsRef.current = null;
      reconnectTimer.current = setTimeout(() => {
        reconnectDelay.current = Math.min(reconnectDelay.current * 1.5, 16000);
        connect();
      }, reconnectDelay.current);
    };

    ws.onerror = () => ws.close();
  }, [wsUrl, send, onAudioChunk]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const startGame = useCallback(
    (mode: "live" | "replay", replayFile?: string) => {
      dispatch({ type: "RESET" });
      send({ type: "start_game", data: { mode, replay_file: replayFile } });
    },
    [send]
  );

  const pause = useCallback(() => send({ type: "control", data: { action: "pause" } }), [send]);
  const resume = useCallback(() => send({ type: "control", data: { action: "resume" } }), [send]);
  const step = useCallback(() => send({ type: "control", data: { action: "step" } }), [send]);
  const setSpeed = useCallback(
    (speed: number) => send({ type: "control", data: { action: "speed", value: speed } }),
    [send]
  );

  return {
    gameState: state,
    isConnected,
    startGame,
    pause,
    resume,
    step,
    setSpeed,
    availableGames,
    dispatch,
  };
}
