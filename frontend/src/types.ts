// Shapes of the messages the replay server sends (see backend/pitch_insights/server.py).

export type Side = "home" | "away";

export interface TeamMeta {
  id: string;
  name: string;
  short_name: string;
  colours: { primary: string; secondary: string };
  formation: string;
  style: string;
  starting: string[];
  bench: string[];
  players: { id: string; name: string; number: number; position: string }[];
}

export interface MatchMeta {
  type: "match_meta";
  match: { id: string; seed: number; competition: string; matchday: number; venue: string };
  home: TeamMeta;
  away: TeamMeta;
  attacking_direction: Record<string, Record<string, "left_to_right" | "right_to_left">>;
}

export interface MatchEvent {
  seq: number;
  t: number;
  period: 1 | 2;
  clock: string;
  minute: number;
  type: string;
  team_id?: string;
  player_id?: string;
  x?: number;
  y?: number;
  end_x?: number;
  end_y?: number;
  outcome?: string;
  kind?: string;
  xg?: number;
  [key: string]: unknown;
}

export interface Fact {
  kind: string;
  text: string;
  value?: unknown;
}

export interface Moment {
  id: string;
  seq: number;
  clock: string;
  minute: number;
  period: number;
  type: string;
  team_id?: string;
  player_id?: string;
  player_name?: string;
  importance: number;
  rank: number; // unclamped importance, for ordering the biggest moments
  tier: "headline" | "notable" | "minor";
  headline: string;
  facts: Fact[];
  signals: string[];
  score: Record<string, number>;
}

export interface PlayerState {
  player_id: string;
  team_id: string;
  name: string;
  number: number;
  position: string;
  minutes: number;
  on_pitch: boolean;
  rating: number;
  goals: number;
  assists: number;
  shots: number;
  xg: number;
  passes: number;
  passes_complete: number;
  key_passes: number;
  tackles_won: number;
  interceptions: number;
  dribbles_won: number;
  saves: number;
  xt_added: number;
  by_category: Record<string, number>;
  key_moments: { clock: string; label: string; delta: number }[];
}

export interface TeamStats {
  possession_pct: number;
  shots: number;
  shots_on_target: number;
  xg: number;
  passes: number;
  pass_accuracy_pct: number;
  progressive_passes: number;
  corners: number;
  pressures_high: number;
  ppda: number | null;
  tackles_won: number;
  interceptions: number;
  fouls: number;
  yellows: number;
  reds: number;
  big_chances: number;
  xt_added: number;
  men: number;
}

export interface LiveState {
  clock: string;
  period: number;
  match_minute: number;
  finished: boolean;
  score: Record<string, number>;
  win_probability: { home: number; draw: number; away: number };
  teams: Record<string, TeamStats>;
  patterns: {
    momentum: number;
    chaos: number;
    tempo: number;
    pressure: Record<string, number>;
    field_tilt: Record<string, number>;
  };
  momentum_series: { period: number; minute: number; clock: string; value: number }[];
  players: PlayerState[];
}

export interface MatchSummary {
  name: string;
  match_id: string;
  home: { id: string; name: string; short_name: string; colours: { primary: string } };
  away: { id: string; name: string; short_name: string; colours: { primary: string } };
}

export type ViewMode = "casual" | "analyst";
