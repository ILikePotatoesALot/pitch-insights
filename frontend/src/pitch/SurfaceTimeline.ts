interface SurfaceFrame { t: number; heights: Float32Array; colours: Float32Array }

/** Surface snapshots sampled on the same buffered clock as the player markers. */
export class SurfaceTimeline {
  readonly heights: Float32Array;
  readonly colours: Float32Array;
  private frames: SurfaceFrame[] = [];
  private revision = 0;
  private sampledRevision = -1;
  private sampledTime = NaN;

  constructor(count: number) {
    this.heights = new Float32Array(count);
    this.colours = new Float32Array(count * 3);
  }

  reset() {
    this.frames = [];
    this.heights.fill(0);
    this.colours.fill(0);
    this.revision++;
    this.sampledTime = NaN;
  }

  push(t: number, heights: Float32Array, colours: Float32Array) {
    const last = this.frames[this.frames.length - 1];
    if (last && t < last.t) this.frames = [];
    if (this.frames[this.frames.length - 1]?.t === t) this.frames.pop();
    this.frames.push({ t, heights: heights.slice(), colours: colours.slice() });
    if (this.frames.length > 16) this.frames.shift();
    this.revision++;
  }

  /** Event-only replays have irregular updates. Ease from the currently drawn surface. */
  transition(t: number, seconds: number, heights: Float32Array, colours: Float32Array) {
    if (!this.frames.length) { this.push(t, heights, colours); return; }
    this.frames = [];
    this.push(t, this.heights, this.colours);
    this.push(t + seconds, heights, colours);
  }

  /** Clamp at the latest snapshot so pauses and a stalled feed settle without drifting. */
  sample(t: number): boolean {
    if (!this.frames.length) return false;
    const last = this.frames.length - 1;
    const at = Math.max(this.frames[0].t, Math.min(t, this.frames[last].t));
    if (at === this.sampledTime && this.revision === this.sampledRevision) return false;
    let i = last;
    while (i > 0 && this.frames[i].t > at) i--;
    const a = this.frames[i], b = this.frames[Math.min(last, i + 1)];
    const k = b.t > a.t ? (at - a.t) / (b.t - a.t) : 0;
    for (let n = 0; n < this.heights.length; n++) this.heights[n] = a.heights[n] + (b.heights[n] - a.heights[n]) * k;
    for (let n = 0; n < this.colours.length; n++) this.colours[n] = a.colours[n] + (b.colours[n] - a.colours[n]) * k;
    this.sampledTime = at;
    this.sampledRevision = this.revision;
    return true;
  }
}
