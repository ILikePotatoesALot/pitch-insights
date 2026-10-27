import type { ClipFrame, MatchMeta } from "../types";

export interface TrackPoint { x: number; y: number }
export interface HistoryPlayer extends TrackPoint { id: string; side: 0 | 1 | 2 }
export interface TrackingSnapshot { t: number; players: Map<string, HistoryPlayer>; ball: TrackPoint | null }
export interface MovementSegment { a: TrackPoint; b: TrackPoint; t: number }

/** Bounded observations, with no invented links across lost tracks or identity jumps. */
export class TrackingHistory {
  private frames: TrackingSnapshot[] = [];

  reset() { this.frames = []; }

  push(frame: ClipFrame, meta: MatchMeta): TrackingSnapshot {
    const dirs = meta.attacking_direction[String(frame.period ?? 1)] ?? {};
    const absolute = (team: string | null, x: number, y: number): TrackPoint =>
      dirs[team ?? frame.ref_team_id] === "right_to_left" ? { x: 105 - x, y: 68 - y } : { x, y };
    const snapshot: TrackingSnapshot = { t: frame.t, players: new Map(),
      ball: frame.ball ? absolute(null, frame.ball.x, frame.ball.y) : null };
    for (const p of frame.players) snapshot.players.set(p.id, { id: p.id, ...absolute(p.team_id, p.x, p.y),
      side: p.team_id === meta.home.id ? 0 : p.team_id === meta.away.id ? 1 : 2 });
    const last = this.frames[this.frames.length - 1];
    if (last && frame.t < last.t) this.reset();
    if (this.frames[this.frames.length - 1]?.t === frame.t) this.frames.pop();
    this.frames.push(snapshot);
    while (this.frames.length > 128 || this.frames[0].t < frame.t - 10) this.frames.shift();
    return snapshot;
  }

  segments(id: string, until: number, head?: TrackPoint): MovementSegment[] {
    const segments: MovementSegment[] = [];
    let previous: (TrackPoint & { t: number }) | null = null;
    const append = (point: TrackPoint, t: number) => {
      if (previous) {
        const dt = t - previous.t;
        const distance = Math.hypot(point.x - previous.x, point.y - previous.y);
        if (dt > 0 && dt <= 0.601 && distance <= 11 * dt + 0.01) segments.push({ a: previous, b: point, t });
      }
      previous = { ...point, t };
    };
    for (const frame of this.frames) {
      if (frame.t < until - 8) continue;
      if (frame.t > until) break;
      const p = frame.players.get(id);
      if (!p) { previous = null; continue; }
      append(p, frame.t);
    }
    if (head && previous) append(head, until);
    return segments;
  }
}
