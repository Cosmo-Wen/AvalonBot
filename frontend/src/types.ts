export type GamePhase =
  | "waiting"
  | "team_selection"
  | "team_voting"
  | "quest_voting"
  | "assassination"
  | "game_over";

export type PlayerRole = "merlin" | "loyal_servant" | "minion" | "assassin";
export type PlayerSide = "good" | "evil";

export interface Player {
  seat: number;
  name: string;
  role?: PlayerRole;
  side?: PlayerSide;
  isSpeaking: boolean;
  audioLevel: number;
}

export interface QuestResult {
  quest: number;
  team: number[];
  success: boolean;
  numFails: number;
}

export interface TeamProposal {
  quest: number;
  round: number;
  leader: number;
  team: number[];
  votes?: Record<number, boolean>;
  approved?: boolean;
}

export type GameEvent =
  | { type: "utterance"; speaker: number; text: string; seq: number }
  | { type: "team_proposed"; leader: number; team: number[]; quest: number; round: number; seq: number }
  | { type: "team_vote_result"; votes: Record<number, boolean>; approved: boolean; quest: number; round: number; seq: number }
  | { type: "quest_result"; quest: number; team: number[]; success: boolean; numFails: number; seq: number }
  | { type: "evil_chat"; speaker: number; text: string; seq: number }
  | { type: "assassination"; assassin: number; target: number; hitMerlin: boolean; seq: number }
  | { type: "game_over"; winner: "good" | "evil"; reason: string; seq: number }
  | { type: "belief_update"; player: number; pEvil: Record<number, number>; seq: number }
  | { type: "audio_chunk"; speaker: number; data: string; seq: number }
  | { type: "role_reveal"; roles: Record<number, PlayerRole>; sides: Record<number, PlayerSide>; seq: number };

export interface BeliefSnapshot {
  seq: number;
  player: number;
  pEvil: Record<number, number>;
}

export interface GameState {
  phase: GamePhase;
  turn: number;
  roundNum: number;
  leader: number;
  players: Player[];
  quests: (QuestResult | null)[];
  currentProposal: TeamProposal | null;
  events: GameEvent[];
  beliefs: Record<number, BeliefSnapshot[]>;
  rolesRevealed: boolean;
}

export interface WSMessage {
  type: string;
  data: Record<string, unknown>;
  seq: number;
}

export const ROLE_DISPLAY: Record<PlayerRole, string> = {
  merlin: "Merlin",
  loyal_servant: "Servant",
  minion: "Minion",
  assassin: "Assassin",
};

export const SEAT_NAMES = ["Atlas", "Lyra", "Griffin", "Phoenix", "Solara"] as const;

export const QUEST_SIZES = [2, 3, 2, 3, 3] as const;

export const SEAT_COLORS = [
  "#c9a84c",
  "#6c9bff",
  "#4cc27e",
  "#e0a83a",
  "#a48bff",
] as const;
