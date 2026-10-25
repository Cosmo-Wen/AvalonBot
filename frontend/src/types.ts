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
  lastUtterance?: string;
}

/** quest is 1-based everywhere in the UI. */
export interface QuestResult {
  quest: number;
  team: number[];
  success: boolean;
  numFails: number;
  seq: number;
}

/** quest is 1-based, round is 0-based (round 4 is the auto-approved hammer). */
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
  | { type: "evil_chat"; speaker: number; text: string; seq: number }
  | { type: "team_proposed"; leader: number; team: number[]; quest: number; round: number; seq: number }
  | { type: "team_vote_result"; votes: Record<number, boolean>; approved: boolean; quest: number; round: number; seq: number }
  | { type: "quest_result"; quest: number; team: number[]; success: boolean; numFails: number; seq: number }
  | { type: "assassination"; assassin: number; target: number; hitMerlin: boolean; seq: number }
  | { type: "game_over"; winner: "good" | "evil"; reason: string; seq: number };

/** One player's memory as the server serializes it (server/memory_view.py). */
export interface MemoryEdge {
  id: number;
  type: "accused" | "defended" | "backed_team" | "opposed_team" | "claimed_role";
  src: number;
  dst: number | string;
  seq: number;
  quest: number;
  quote: string;
  sources: number[];
  role: string;
}

export interface MemoryFlag {
  talk: number;
  voteSeq: number;
  team: string;
}

export interface MemoryTeam {
  label: string;
  quest: number;
  attempt: number;
  leader: number;
  members: number[];
  votes: Record<string, boolean>;
  approved: boolean | null;
  fails: number | null;
  success: boolean | null;
}

export interface PlayerMemoryView {
  owner: number;
  role: string;
  side: "Good" | "Evil";
  seenEvil: number[];
  beliefName: "P(evil)" | "P(Merlin)" | null;
  beliefs: Record<string, number>;
  consistent: boolean;
  constraints: string[];
  cards: Record<string, boolean>;
  edges: MemoryEdge[];
  flags: MemoryFlag[];
  teams: MemoryTeam[];
  notes: Record<string, string>;
  logSize: number;
}

export interface BeliefSnapshot {
  seq: number;
  values: Record<number, number>;
}

export interface HumanRoleInfo {
  seat: number;
  role: string;
  side: "good" | "evil";
  seenPlayers: number[];
  evilPlayers: number[];
}

export interface HumanActionPrompt {
  action: "discussion" | "propose_team" | "vote_on_team" | "vote_on_quest" | "evil_discussion" | "assassinate";
  seat: number;
  turn?: number;
  roundNum?: number;
  leader?: number;
  team?: number[];
  teamSize?: number;
  canFail?: boolean;
  side?: "good" | "evil";
  candidates?: number[];
}

export interface GameState {
  mode: "live" | "replay" | null;
  phase: GamePhase;
  turn: number;
  roundNum: number;
  leader: number;
  players: Player[];
  quests: (QuestResult | null)[];
  currentProposal: TeamProposal | null;
  lastVote: TeamProposal | null;
  events: GameEvent[];
  memory: Record<number, PlayerMemoryView>;
  beliefHistory: Record<number, BeliefSnapshot[]>;
  rolesKnown: boolean;
  violations: string[];
  error: string | null;
  finished: boolean;
  humanSeat: number | null;
  humanRole: HumanRoleInfo | null;
  humanPrompt: HumanActionPrompt | null;
}

export const ROLE_DISPLAY: Record<PlayerRole, string> = {
  merlin: "Merlin",
  loyal_servant: "Servant",
  minion: "Minion",
  assassin: "Assassin",
};

export const SEAT_NAMES = ["Atlas", "Lyra", "Griffin", "Phoenix", "Solara"] as const;

export const QUEST_SIZES = [2, 3, 2, 3, 3] as const;

export const SEAT_COLORS = ["#c9a84c", "#6c9bff", "#4cc27e", "#e0a83a", "#a48bff"] as const;

export function seatName(seat: number): string {
  return SEAT_NAMES[seat] ?? `Seat ${seat}`;
}
