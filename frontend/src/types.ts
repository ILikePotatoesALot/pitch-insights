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
  source?: "video"; // set for the real-footage clip: two sides, no squads, colours used as given
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
  commentary?: Commentary; // written by the agents, when there is some for this moment
  lang?: string; // set when the server sent this moment machine-translated
}

/** One moment's commentary from the agents, checked against its evidence pack. */
export interface Commentary {
  moment_id: string;
  agent: "explainer" | "narrator" | "video_narrator";
  status: "ok" | "fallback";
  casual: string;
  analyst: string;
  attempts: number;
  grounding: { score: number; claims: number; unsupported: string[] } | null;
  corrected: string[]; // what the groundedness check caught in an earlier draft
  reason: string | null;
  safety?: { passed: boolean; severities: Record<string, number>; flagged: string[]; error: string | null } | null;
}

/** Who wrote a match's stored commentary, for the AI-generated label. */
export interface CommentaryInfo {
  ai_generated: boolean;
  provider: string;
  model: string;
  prompt_version: string;
  summary: { moments: number; ok: number; fallback: number; retried: number; grounding_mean: number | null };
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
  kind?: "synthetic" | "video"; // a tracked clip of real footage is "video"
  match_id: string;
  home: { id: string; name: string; short_name: string; colours: { primary: string } };
  away: { id: string; name: string; short_name: string; colours: { primary: string } };
}

export type ViewMode = "casual" | "analyst";
/** Broadcast shows the pitch and its overlays only; fan adds the side panel. */
export type LayoutMode = "broadcast" | "fan";

export type CueTemplate = "lower_third" | "stat_card" | "player_tag" | "rating_alert" | "speed_popup" | "fan_alert";

/**
 * An overlay the Overlay Director chose to show (see backend/pitch_insights/director/cues.py). The server
 * decides when it starts and ends (`cue` and `cue_end` messages), so the app only draws what it is told.
 * Text from commentary arrives already in the viewer's language; labels such as "Possession" are the app's.
 */
export interface Cue {
  id: string;
  time: number; // match seconds of what it is about
  duration: number; // seconds on screen
  priority: number; // 0-100
  template: CueTemplate;
  tier: Moment["tier"];
  detail: ViewMode; // "analyst" cues are for analysts only
  about: { team_id: string | null; player_id: string | null };
  topic: string | null;
  why?: "favourite_player" | "favourite_club"; // set when the viewer's profile is why it is here or boosted
  moment_id: string | null;
  delay?: number; // seconds it waited for a free slot
  data: Record<string, any>;
}

// ---------------------------------------------------------------- Personalise

/** The stat a viewer cares most about; the keys are the ones the team stats and stat-card rows use. */
export type FocusMetric = "win_probability" | "xt_added" | "xg" | "pass_accuracy_pct" | "possession_pct" | "shots";

/**
 * What a viewer chooses, and the only thing stored about them: no name, id or history (see profile.ts). The
 * server checks the club, player, mode and focus against the match (backend/pitch_insights/director/personalise.py).
 */
export interface Profile {
  version: 1;
  mode: ViewMode;
  lang: string;
  team: string | null; // favourite club id
  player: string | null; // favourite player id
  focus: FocusMetric | null;
}

/** A club and its squad, from GET /api/clubs, for the profile picker. */
export interface ClubInfo {
  id: string;
  name: string;
  short_name: string;
  colours: { primary: string; secondary: string };
  players: { id: string; name: string; number: number; position: string }[];
}

// ---------------------------------------------------------------- Video clip

/** One person in a `frame` message, in their own team's attacking frame (see DESIGN.md, Video path). */
export interface ClipPlayer { id: string; team_id: string | null; x: number; y: number; speed: number | null; confidence: number }

/** Positions of everyone at one moment of the clip; `t` is seconds since the half started. */
export interface ClipFrame {
  type: "frame";
  t: number;
  clock: string;
  ref_team_id: string;
  players: ClipPlayer[];
  ball: { x: number; y: number; confidence: number } | null;
}

/** An event the video path detected (a pass, carry or interception), with a confidence below 1. */
export interface ClipEvent extends MatchEvent { source: "video"; confidence: number; receiver_id?: string }

/** The events as the viewer reads them: the server's words, in the viewer's language. */
export interface ClipEventLine { event: ClipEvent; text: string }

/** What the credibility panel shows: from the benchmark file, with the credit and what the figures don't cover. */
export interface ClipInfo {
  clip: { match: string; from: string; to: string; frames: number; fps: number; start: number; duration: number };
  model: string;
  fine_tuned: boolean;
  tiles: string | null;
  credit: string;
  credit_url: string;
  figures: {
    precision: number; recall: number; position_error_mean_m: number; position_error_median_m: number;
    position_error_p90_m: number; team_accuracy: number; id_consistency: number; tracks: number;
    players_on_pitch: number; match_radius_m: number; ball_frames: number; frames: number;
    event_precision: number; event_recall: number;
  };
  limits: string[];
}
