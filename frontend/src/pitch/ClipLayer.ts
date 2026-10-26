import * as THREE from "three";
import type { ClipEvent, ClipFrame, MatchMeta } from "../types";

const L = 105;
const W = 68;
const GREY = "#5f6f7d"; // people the model could not give a team (keepers, officials)
const MAX_SNAPSHOTS = 12;
const LAG_FRAMES = 1.5; // the picture trails the stream by this many frame intervals, to ride out a late frame
const MAX_STEP_MS = 250; // the most real time one draw may add to the clock (a hidden tab wakes up with a big gap)
const EASE_BACK = 0.95; // while the clock is more than half a frame interval ahead of its usual lag (after a late frame), it runs a little slow to recover it
const EVENT_SECONDS = 3.5; // how long a pass line or interception ring stays on the pitch, in clip seconds
const HOLD_BALL_S = 1.2; // how long the last known ball position stays up (dimmed) after the ball is lost

/** "L-t12" is "Left #12"; a track with no team is "Track #5". Never a name: the video can't read any. */
export function trackLabel(id: string): string {
  const m = /^([A-Z])-t(\d+)$/.exec(id);
  if (!m) return "Unknown";
  return m[1] === "L" ? `Left #${m[2]}` : m[1] === "R" ? `Right #${m[2]}` : `Track #${m[2]}`;
}

interface Pt { x: number; z: number; team: 0 | 1 | 2; speed: number | null; conf: number }
interface Snap { t: number; players: Map<string, Pt>; ball: { x: number; z: number } | null }
interface Marker { id: string; group: THREE.Group; label: THREE.Sprite; team: 0 | 1 | 2 }
interface EventMark { line: THREE.Line; ring: THREE.Mesh; born: number; from: THREE.Vector2 | null; to: THREE.Vector2; active: boolean }

/** Pitch metres in the viewer's absolute frame (home attacking left to right) to scene coordinates. */
const scenePoint = (ax: number, ay: number) => new THREE.Vector2(ax - L / 2, W / 2 - ay);

/**
 * The tracked players and ball of a video clip, drawn on the 3D pitch.
 *
 * Frames arrive a few times a second (as the server's replay clock releases them), so the layer keeps the last
 * few and draws the pitch a little in the past, between the two frames either side of that moment, moving
 * everyone in a straight line from one to the next. That is smooth at any replay speed, and a pause simply
 * lets the drawing catch up with the last frame. Positions come in the clip's own frames (each team's
 * attacking direction) and are converted here with the match meta's attacking directions.
 */
export class ClipLayer {
  readonly group = new THREE.Group();
  private snaps: Snap[] = [];
  private clock: { t: number; at: number } | null = null; // the time being drawn (clip seconds), and when (performance.now) it was set
  private markers = new Map<string, Marker>();
  private mats: THREE.MeshStandardMaterial[];
  private ball: THREE.Mesh;
  private ballLast: { x: number; z: number; t: number } | null = null;
  private labels = new Map<string, THREE.CanvasTexture>();
  private marks: EventMark[] = [];
  private colours: THREE.Color[] = [];
  private bodyGeo = new THREE.CapsuleGeometry(0.7, 1.3, 4, 10);
  private tmp = new THREE.Vector3();
  private current = new Map<string, { x: number; z: number; y: number; speed: number | null; conf: number }>();

  constructor(private heightAt: (x: number, z: number) => number) {
    this.mats = [0, 1, 2].map(() => new THREE.MeshStandardMaterial({ roughness: 0.5, metalness: 0.1 }));
    this.ball = new THREE.Mesh(new THREE.SphereGeometry(0.9, 20, 16),
      new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 0.6, transparent: true }));
    this.ball.visible = false;
    this.group.add(this.ball);
    this.group.visible = false;
  }

  /** Team colours: [Left, Right]. Teamless markers are grey. */
  setColours(home: THREE.Color, away: THREE.Color) {
    this.colours = [home, away, new THREE.Color(GREY)];
    this.mats.forEach((m, i) => { m.color.copy(this.colours[i]); m.emissive.copy(this.colours[i]).multiplyScalar(0.45); });
    for (const mk of this.markers.values()) this.paintLabel(mk);
  }

  /** The frame as a snapshot in scene coordinates (its players' own attacking frames made absolute). */
  push(frame: ClipFrame, meta: MatchMeta) {
    const dirs = meta.attacking_direction["1"] ?? {};
    const toScene = (team: string | null, x: number, y: number) => {
      const flip = dirs[team ?? frame.ref_team_id] === "right_to_left";
      return scenePoint(flip ? L - x : x, flip ? W - y : y);
    };
    const players = new Map<string, Pt>();
    for (const p of frame.players) {
      const s = toScene(p.team_id, p.x, p.y);
      players.set(p.id, { x: s.x, z: s.y, team: p.team_id === meta.home.id ? 0 : p.team_id === meta.away.id ? 1 : 2,
                          speed: p.speed, conf: p.confidence });
    }
    const b = frame.ball ? toScene(null, frame.ball.x, frame.ball.y) : null;
    this.snaps.push({ t: frame.t, players, ball: b ? { x: b.x, z: b.y } : null });
    if (this.snaps.length > MAX_SNAPSHOTS) this.snaps.shift();
    this.group.visible = true;
  }

  /** The frame's players as pitch coordinates for the territory heat, by side (0 Left, 1 Right). */
  lastPlayers(): { side: 0 | 1; x: number; y: number }[] {
    const s = this.snaps[this.snaps.length - 1];
    if (!s) return [];
    return [...s.players.values()].filter((p) => p.team !== 2).map((p) => ({ side: p.team as 0 | 1, x: p.x + L / 2, y: W / 2 - p.z }));
  }

  /** A detected event: a line for a pass or carry, a ring where an interception happened, fading with clip time. */
  addEvent(ev: ClipEvent, meta: MatchMeta) {
    const dirs = meta.attacking_direction["1"] ?? {};
    const flip = dirs[ev.team_id ?? ""] === "right_to_left";
    const at = (x: number, y: number) => scenePoint(flip ? L - x : x, flip ? W - y : y);
    const home = ev.team_id === meta.home.id;
    const colour = this.colours[home ? 0 : ev.team_id === meta.away.id ? 1 : 2] ?? new THREE.Color(GREY);
    const to = ev.end_x !== undefined && ev.end_y !== undefined ? at(ev.end_x, ev.end_y) : null;
    const from = at(ev.x!, ev.y!);
    let mark = this.marks.find((m) => !m.active);
    if (!mark) {
      const geo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]);
      const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ transparent: true, depthTest: false }));
      const ring = new THREE.Mesh(new THREE.RingGeometry(1.8, 2.5, 40), new THREE.MeshBasicMaterial({
        side: THREE.DoubleSide, transparent: true, depthWrite: false }));
      ring.rotation.x = -Math.PI / 2;
      line.renderOrder = ring.renderOrder = 5;
      line.frustumCulled = false; // its end points move, but the bounding sphere is measured once, at the origin
      this.group.add(line, ring);
      mark = { line, ring, born: 0, from: null, to: from, active: false };
      this.marks.push(mark);
    }
    (mark.line.material as THREE.LineBasicMaterial).color.copy(colour);
    (mark.ring.material as THREE.MeshBasicMaterial).color.copy(colour);
    Object.assign(mark, { born: ev.t, from: to ? from : null, to: to ?? from, active: true });
    mark.line.visible = !!to;
    mark.ring.visible = !to;
  }

  /** The id of the marker nearest a point on the page (CSS pixels in the pitch box), within `radius`, or null. */
  pick(px: number, py: number, camera: THREE.Camera, w: number, h: number, radius = 22): string | null {
    let best: string | null = null, bestD = radius * radius;
    for (const [id, p] of this.current) {
      const v = this.tmp.set(p.x, p.y + 1, p.z).project(camera);
      const d = ((v.x * 0.5 + 0.5) * w - px) ** 2 + ((-v.y * 0.5 + 0.5) * h - py) ** 2;
      if (d < bestD) { best = id; bestD = d; }
    }
    return best;
  }

  /** Where a tracked person is drawn now (scene x and z), or undefined if the tracker hasn't got them. */
  positionOf(id: string): { x: number; z: number } | undefined {
    return this.current.get(id);
  }

  clear() {
    this.snaps = [];
    this.clock = null;
    this.ballLast = null;
    this.current.clear();
    for (const m of this.markers.values()) m.group.visible = false;
    for (const m of this.marks) { m.active = false; m.line.visible = m.ring.visible = false; }
    this.ball.visible = false;
    this.group.visible = false;
  }

  /** Draw the clip as of now. Call once per rendered frame. */
  update(speed: number, now = performance.now()) {
    const n = this.snaps.length;
    if (!n) return;
    const last = this.snaps[n - 1];
    const gap = n > 1 ? Math.max(0.2, last.t - this.snaps[n - 2].t) : 0.2;
    // The picture trails the stream by a frame and a half, so there is nearly always a next frame to move towards
    // even when one arrives a little late. The clock runs on by itself at the replay speed and only moves forward:
    // a late frame (which lowers the usual lag) can't pull it back and make players jump backwards. It is lifted
    // to the usual lag if it has fallen behind, and held at the newest frame if the stream runs dry, so a pause
    // settles on that frame.
    const usual = last.t - LAG_FRAMES * gap;
    let rt = usual;
    if (this.clock) {
      const ahead = this.clock.t - usual;
      rt = this.clock.t + (Math.min(MAX_STEP_MS, Math.max(0, now - this.clock.at)) / 1000) * speed * (ahead > 0.5 * gap ? EASE_BACK : 1);
    }
    rt = Math.min(last.t, Math.max(rt, usual));
    this.clock = { t: rt, at: now };
    let i = n - 1;
    while (i > 0 && this.snaps[i].t > rt) i--;
    const a = this.snaps[i], b = this.snaps[Math.min(n - 1, i + 1)];
    const k = b.t > a.t ? Math.min(1, Math.max(0, (rt - a.t) / (b.t - a.t))) : 0;
    const near = k < 0.5 ? a : b;
    const seen = new Set<string>();
    for (const [id, p] of near.players) {
      const other = (near === a ? b : a).players.get(id);
      const kk = near === a ? k : 1 - k; // how far towards the other snapshot
      const x = other ? p.x + (other.x - p.x) * kk : p.x;
      const z = other ? p.z + (other.z - p.z) * kk : p.z;
      const y = this.heightAt(x, z);
      const at = this.current.get(id);
      if (at) Object.assign(at, { x, z, y, speed: p.speed, conf: p.conf }); // updated in place: no garbage per frame
      else this.current.set(id, { x, z, y, speed: p.speed, conf: p.conf });
      seen.add(id);
      const mk = this.marker(id, p.team);
      mk.group.visible = true;
      mk.group.position.set(x, y + 1.35, z);
    }
    for (const id of this.current.keys()) if (!seen.has(id)) this.current.delete(id);
    for (const [id, mk] of this.markers) if (!seen.has(id)) mk.group.visible = false;
    this.moveBall(a, b, k, rt);
    this.moveMarks(rt);
  }

  dispose() {
    this.group.traverse((o) => {
      if (o instanceof THREE.Mesh || o instanceof THREE.Line) {
        o.geometry.dispose();
        for (const m of Array.isArray(o.material) ? o.material : [o.material]) m.dispose();
      }
      if (o instanceof THREE.Sprite) o.material.dispose();
    });
    for (const t of this.labels.values()) t.dispose();
    this.mats.forEach((m) => m.dispose());
    this.bodyGeo.dispose();
  }

  // ------------------------------------------------------------ internals

  private marker(id: string, team: 0 | 1 | 2): Marker {
    let mk = this.markers.get(id);
    if (mk && mk.team !== team) { // a track that got a team after it first appeared
      this.group.remove(mk.group);
      mk = undefined;
    }
    if (!mk) {
      const body = new THREE.Mesh(this.bodyGeo, this.mats[team]);
      const label = new THREE.Sprite(new THREE.SpriteMaterial({ depthTest: false, transparent: true }));
      label.scale.set(3.4, 1.7, 1);
      label.position.y = 2.6;
      label.renderOrder = 6;
      const group = new THREE.Group();
      group.add(body, label);
      this.group.add(group);
      mk = { id, group, label, team };
      this.markers.set(id, mk);
      this.paintLabel(mk);
    }
    return mk;
  }

  private paintLabel(mk: Marker) {
    const text = mk.id.slice(mk.id.lastIndexOf("t") + 1); // the tracker number: "L-t12" is "12"
    const hex = `#${(this.colours[mk.team] ?? new THREE.Color(GREY)).getHexString()}`;
    const tex = this.labels.get(`${text}|${hex}`) ?? this.makeLabel(text, hex);
    this.labels.set(`${text}|${hex}`, tex);
    (mk.label.material as THREE.SpriteMaterial).map = tex;
    mk.label.material.needsUpdate = true;
  }

  private makeLabel(text: string, colour: string): THREE.CanvasTexture {
    const c = document.createElement("canvas");
    c.width = 128;
    c.height = 64;
    const g = c.getContext("2d")!;
    g.fillStyle = "rgba(11,18,24,0.82)";
    g.beginPath();
    g.roundRect(8, 8, 112, 48, 14);
    g.fill();
    g.strokeStyle = colour;
    g.lineWidth = 5;
    g.stroke();
    g.fillStyle = "#e8eef3";
    g.font = "700 30px Segoe UI, system-ui, sans-serif";
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.fillText(text, 64, 34);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  }

  /** The ball where it was last seen: solid while it is detected, dimmed for a moment after, then gone. */
  private moveBall(a: Snap, b: Snap, k: number, rt: number) {
    const detected = a.ball && b.ball ? { x: a.ball.x + (b.ball.x - a.ball.x) * k, z: a.ball.z + (b.ball.z - a.ball.z) * k }
      : (k < 0.5 ? a.ball : b.ball);
    if (detected) this.ballLast = { ...detected, t: rt };
    const shown = detected ?? (this.ballLast && rt - this.ballLast.t >= 0 && rt - this.ballLast.t < HOLD_BALL_S ? this.ballLast : null);
    this.ball.visible = !!shown;
    if (!shown) return;
    this.ball.position.set(shown.x, this.heightAt(shown.x, shown.z) + 1.4, shown.z);
    (this.ball.material as THREE.MeshStandardMaterial).opacity = detected ? 1 : 0.35;
  }

  private moveMarks(rt: number) {
    for (const m of this.marks) {
      if (!m.active) continue;
      const age = rt - m.born;
      if (age > EVENT_SECONDS) { m.active = false; m.line.visible = m.ring.visible = false; continue; }
      const alpha = Math.max(0, Math.min(1, 1 - age / EVENT_SECONDS)) * 0.9;
      if (m.line.visible && m.from) {
        const pos = m.line.geometry.getAttribute("position") as THREE.BufferAttribute;
        pos.setXYZ(0, m.from.x, this.heightAt(m.from.x, m.from.y) + 0.6, m.from.y);
        pos.setXYZ(1, m.to.x, this.heightAt(m.to.x, m.to.y) + 0.6, m.to.y);
        pos.needsUpdate = true;
        (m.line.material as THREE.LineBasicMaterial).opacity = alpha;
      } else {
        m.ring.position.set(m.to.x, this.heightAt(m.to.x, m.to.y) + 0.5, m.to.y);
        m.ring.scale.setScalar(1 + Math.max(0, age) * 0.5);
        (m.ring.material as THREE.MeshBasicMaterial).opacity = alpha;
      }
    }
  }
}
