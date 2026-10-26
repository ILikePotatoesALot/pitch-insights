import type { ClipFrame, MatchMeta } from "./types";

const L = 105;
const W = 68;
const MAX_GAP_S = 0.5; // frames further apart than this (a seek, a skipped frame) don't add distance
const MAX_SPEED = 11; // m/s: a faster step is a tracker ID jumping to another player, not running
const TOP_SPEED = 9.5; // m/s (34 km/h): a faster reading is an ID switch too (DESIGN.md: they reach 11.7 m/s)
const HELD_FRAMES = 3; // a top speed must hold this many frames in a row (0.6 s), so one jumpy reading doesn't count
const BALL_RADIUS_M = 3; // the side with a player this close to the ball has it

/** What the tracking says about one tracked person since the viewer started watching. */
export interface TrackStats {
  id: string;
  side: 0 | 1 | null; // Left, Right, or no team
  distance: number;   // metres
  topSpeed: number;   // m/s
  speed: number | null; // m/s, in the latest frame
  confidence: number;
  seen: boolean;      // in the latest frame
}

export interface ClipTracking {
  players: TrackStats[];
  possession: [number, number]; // frames each side was nearest the ball (within BALL_RADIUS_M)
}

/**
 * Running totals from the clip's frames: distance and top speed per tracked person, and which side was nearest
 * the ball. Positions come in each team's own attacking frame and are turned into one frame first, as the pitch
 * layer does. Starts again on a seek (the server sends frames only from there).
 */
export class TrackingTotals {
  private stats = new Map<string, TrackStats>();
  private last = new Map<string, { x: number; y: number; t: number }>();
  private recent = new Map<string, number[]>(); // each person's last few speed readings
  private near: [number, number] = [0, 0];

  reset() {
    this.stats.clear();
    this.last.clear();
    this.recent.clear();
    this.near = [0, 0];
  }

  push(frame: ClipFrame, meta: MatchMeta) {
    const dirs = meta.attacking_direction["1"] ?? {};
    const abs = (team: string | null, x: number, y: number): [number, number] =>
      dirs[team ?? frame.ref_team_id] === "right_to_left" ? [L - x, W - y] : [x, y];
    for (const s of this.stats.values()) s.seen = false;
    let nearest: { side: 0 | 1 | null; d: number } | null = null;
    const ball = frame.ball ? abs(null, frame.ball.x, frame.ball.y) : null;
    for (const p of frame.players) {
      const side = p.team_id === meta.home.id ? 0 : p.team_id === meta.away.id ? 1 : null;
      const [x, y] = abs(p.team_id, p.x, p.y);
      const s = this.stats.get(p.id) ?? { id: p.id, side, distance: 0, topSpeed: 0, speed: null, confidence: 0, seen: false };
      const prev = this.last.get(p.id);
      if (prev) {
        const dt = frame.t - prev.t, step = Math.hypot(x - prev.x, y - prev.y);
        if (dt > 0 && dt <= MAX_GAP_S && step / dt <= MAX_SPEED) s.distance += step;
      }
      const speeds = [...(this.recent.get(p.id) ?? []), p.speed ?? Infinity].slice(-HELD_FRAMES);
      this.recent.set(p.id, speeds);
      const held = Math.min(...speeds); // the speed kept up over the last few frames
      if (speeds.length === HELD_FRAMES && held <= TOP_SPEED) s.topSpeed = Math.max(s.topSpeed, held);
      Object.assign(s, { side, speed: p.speed, confidence: p.confidence, seen: true });
      this.stats.set(p.id, s);
      this.last.set(p.id, { x, y, t: frame.t });
      if (ball) {
        const d = Math.hypot(x - ball[0], y - ball[1]);
        if (!nearest || d < nearest.d) nearest = { side, d };
      }
    }
    if (nearest && nearest.side !== null && nearest.d <= BALL_RADIUS_M) this.near[nearest.side]++;
  }

  snapshot(): ClipTracking {
    return { players: [...this.stats.values()].map((s) => ({ ...s })), possession: [...this.near] as [number, number] };
  }
}
