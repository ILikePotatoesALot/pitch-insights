export interface FormationPoint { id: string; depth: number }
export interface FormationShape { lines: string[][]; label: string }

const SAMPLE_SECONDS = 0.25;
const SETTLE_SECONDS = 1.5;
const LINE_COST = 85; // squared metres: an extra band must explain a meaningful depth difference
const MIN_SEPARATION = 7;

/** Fit two to four depth bands, without prescribing a team's starting formation. */
export function inferShape(points: FormationPoint[]): FormationShape | null {
  if (points.length !== 10 || points.some((p) => !Number.isFinite(p.depth))) return null;
  const sorted = [...points].sort((a, b) => a.depth - b.depth || a.id.localeCompare(b.id));
  if (sorted[9].depth - sorted[0].depth < 14) return null;
  let best: { lines: FormationPoint[][]; score: number } | null = null;
  // Ten outfield players give at most 84 partitions into four contiguous bands.
  const visit = (lines: FormationPoint[][], start: number, score: number) => {
    if (start === sorted.length) {
      if (lines.length >= 2 && (!best || score < best.score)) best = { lines, score };
      return;
    }
    if (lines.length === 4) return;
    const previous = lines[lines.length - 1];
    const previousMean = previous && previous.reduce((sum, p) => sum + p.depth, 0) / previous.length;
    for (let end = start + 1; end <= sorted.length; end++) {
      const line = sorted.slice(start, end);
      const mean = line.reduce((sum, p) => sum + p.depth, 0) / line.length;
      if (previous && mean - previousMean < MIN_SEPARATION) continue;
      const cost = line.reduce((sum, p) => sum + (p.depth - mean) ** 2, 0);
      visit([...lines, line], end, score + cost + LINE_COST);
    }
  };
  visit([], 0, 0);
  const result = best as { lines: FormationPoint[][]; score: number } | null;
  if (!result) return null;
  const lines = result.lines.map((line) => line.map((p) => p.id));
  return { lines, label: lines.map((line) => line.length).join("-") };
}

const signature = (shape: FormationShape) => shape.lines.map((line) => [...line].sort().join(",")).join("|");

/** Smooth measured depth and require persistent membership changes, using replay seconds only. */
export class FormationTracker {
  private depths = new Map<string, number>();
  private lastTime: number | null = null;
  private sampledAt = Number.NEGATIVE_INFINITY;
  private pending: { key: string; since: number } | null = null;
  private shape: FormationShape | null = null;

  reset() {
    this.depths.clear();
    this.lastTime = null;
    this.sampledAt = Number.NEGATIVE_INFINITY;
    this.pending = null;
    this.shape = null;
  }

  update(t: number, points: FormationPoint[]): FormationShape | null {
    if (!Number.isFinite(t) || points.length !== 10 || new Set(points.map((p) => p.id)).size !== 10 ||
        points.some((p) => !Number.isFinite(p.depth))) { this.reset(); return null; }
    if (this.lastTime !== null && (t < this.lastTime || t - this.lastTime > 1.5 ||
        points.some((p) => !this.depths.has(p.id)))) this.reset();
    const elapsed = this.lastTime === null ? 0 : t - this.lastTime;
    const blend = 1 - Math.exp(-elapsed / 0.6);
    for (const p of points) {
      const previous = this.depths.get(p.id);
      this.depths.set(p.id, previous === undefined ? p.depth : previous + (p.depth - previous) * blend);
    }
    this.lastTime = t;
    if (t - this.sampledAt < SAMPLE_SECONDS) return this.shape;
    this.sampledAt = t;
    const proposed = inferShape(points.map((p) => ({ id: p.id, depth: this.depths.get(p.id)! })));
    if (!proposed) { this.shape = null; this.pending = null; return null; }
    const key = signature(proposed);
    if (!this.shape) { this.shape = proposed; this.pending = null; }
    else if (signature(this.shape) === key) this.pending = null;
    else if (this.pending?.key !== key) this.pending = { key, since: t };
    else if (t - this.pending.since >= SETTLE_SECONDS) { this.shape = proposed; this.pending = null; }
    return this.shape;
  }
}
