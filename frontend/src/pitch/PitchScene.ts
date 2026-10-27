import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { ClipEvent, ClipFrame, MatchEvent, MatchMeta } from "../types";
import { ClipLayer } from "./ClipLayer";
import { SurfaceTimeline } from "./SurfaceTimeline";
import { PlayerContextLayer, type PlayerContextOptions } from "./PlayerContextLayer";
import { FormationLayer, type FormationLabels, type FormationTeam } from "./FormationLayer";
import type { TrackPoint } from "./TrackingHistory";
import { cameraFocus, cameraBlend, type CameraMode } from "./CameraFollow";

export type SurfaceView = "current" | "history";

const L = 105;
const W = 68;
const NX = 105; // grid cells along the length (1 m each)
const NZ = 68;
const TERRITORY_TAU = 120; // seconds of match time for activity to fade to ~37%
const CURRENT_TAU = 3; // recent movement responds quickly, separately from the activity history
const SPIKE_TAU = 10;
const SPIKE_RISE_S = 0.35;
const GOAL_GLOW_TAU = 3;
const SIGMA = 7; // metres: how far one action's influence spreads
const CLIP_HEAT_PER_S = 0.015; // territory a tracked player adds each second, at their spot (an event adds 0.2 to 0.9)
const PICK_DRAG_PX = 5; // a press that moves further than this is a camera drag, not a tap on a player
const VIEW_ELEVATION = (40 * Math.PI) / 180; // the default camera: centred on the halfway line, 40 degrees above the pitch
const GOAL_W = 7.32;
const GOAL_H = 2.44;
const GOAL_D = 2;
const TRAIL = 6; // touches shown behind the ball

/** Event position in absolute pitch metres, with the home team attacking left to right in the first half. */
export function toAbsolute(ev: MatchEvent, meta: MatchMeta, end = false): [number, number] | null {
  const x = end ? ev.end_x : ev.x;
  const y = end ? ev.end_y : ev.y;
  if (x === undefined || y === undefined || !ev.team_id) return null;
  const dir = meta.attacking_direction[String(ev.period)]?.[ev.team_id];
  return dir === "right_to_left" ? [L - x, W - y] : [x, y];
}

function displayColour(hex: string): THREE.Color {
  const c = new THREE.Color(hex);
  const hsl = { h: 0, s: 0, l: 0 };
  c.getHSL(hsl);
  // Dark club colours vanish on a dark background, so lift them; keep very light ones off pure white.
  c.setHSL(hsl.h, Math.max(hsl.s, 0.35), Math.min(0.72, Math.max(hsl.l, 0.5)));
  return c;
}

/** Pick display colours for the two teams that are easy to tell apart. */
export function teamColours(meta: MatchMeta): [THREE.Color, THREE.Color] {
  // The real clip's sides are blue and white: shown as they are, since lifting a white shirt's colour would make
  // it a second blue.
  if (meta.source === "video") return [new THREE.Color(meta.home.colours.primary), new THREE.Color(meta.away.colours.primary)];
  const home = displayColour(meta.home.colours.primary);
  let away = displayColour(meta.away.colours.primary);
  const diff = Math.abs(home.r - away.r) + Math.abs(home.g - away.g) + Math.abs(home.b - away.b);
  if (diff < 0.5) away = displayColour(meta.away.colours.secondary);
  return [home, away];
}

interface Spike { x: number; y: number; amp: number; born: number; goal: boolean }

/** A ring and a beam that follow one player, and the page's label for them. See PitchScene.setSpotlight. */
interface Spotlight { id: string; colour: string; group: THREE.Group; pulse: THREE.Mesh; label: HTMLElement | null; target: THREE.Vector3; placed: boolean; on: boolean; labelSize: [number, number] }

const BASE_COLOUR = new THREE.Color("#10202c");
const CONTESTED_COLOUR = new THREE.Color("#5d6b7d"); // space neither team owns: slate, not a muddy mix of the two colours
const GLOW_COLOUR = new THREE.Color("#fff6c2");

export class PitchScene {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private controls: OrbitControls;
  private geometry: THREE.BufferGeometry;
  private heat: [Float32Array, Float32Array];
  private recentHeat: [Float32Array, Float32Array] = [new Float32Array((NX + 1) * (NZ + 1)), new Float32Array((NX + 1) * (NZ + 1))];
  private instantHeat: [Float32Array, Float32Array] = [new Float32Array((NX + 1) * (NZ + 1)), new Float32Array((NX + 1) * (NZ + 1))];
  private surfaceView: SurfaceView = "current";
  private currentBall: TrackPoint | null = null;
  private context: PlayerContextLayer;
  private formation: FormationLayer;
  private contextOptions: PlayerContextOptions = { trail: true, nearby: true };
  private spikes: Spike[] = [];
  private ball: THREE.Mesh;
  private ballTarget = new THREE.Vector3(0, 1, 0);
  private matchTime = 0;
  private lastDecayTime = 0;
  private colours: [THREE.Color, THREE.Color] = [new THREE.Color("#4f7cff"), new THREE.Color("#ff5a5a")];
  private homeId = "";
  private frame = 0;
  private observer: ResizeObserver;
  private dirty = true;
  private surface = new SurfaceTimeline((NX + 1) * (NZ + 1));
  private surfaceHeights = new Float32Array((NX + 1) * (NZ + 1));
  private surfaceColours = new Float32Array((NX + 1) * (NZ + 1) * 3);
  private tmpColour = new THREE.Color();
  private spot: Spotlight | null = null;
  private playerPositions = new Map<string, [number, number]>();
  private tmpVector = new THREE.Vector3();
  private clip: ClipLayer;
  private clipSpeed = 1;
  private onPick: ((id: string) => void) | null = null;
  private lastFrameT: number | null = null;
  private pressAt: [number, number] | null = null;
  private movedBeforePress = false;
  private goals: THREE.Group[] = [];
  private touches: { x: number; y: number; side: number }[] = [];
  private trailDots: THREE.Mesh[] = [];
  private trailLine: THREE.Line;
  private userMoved = false; // once the viewer turns or zooms, a resize no longer reframes the pitch
  private flyTo: { position: THREE.Vector3; target: THREE.Vector3 } | null = null;
  private cameraMode: CameraMode = "full";
  private cameraModeChanged: ((mode: CameraMode) => void) | null = null;
  private followOffset = new THREE.Vector3();
  private followTarget = new THREE.Vector3();
  private lastCameraAt: number | null = null;

  constructor(private container: HTMLElement) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(this.renderer.domElement);

    this.camera = new THREE.PerspectiveCamera(38, 1, 1, 1000);
    this.camera.position.set(0, 72, 86); // replaced by the fitted view on the first resize
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(0, 0, 0);
    this.controls.enableDamping = true;
    this.controls.maxPolarAngle = Math.PI * 0.45;
    this.controls.minDistance = 40;
    this.controls.maxDistance = 220;
    this.controls.addEventListener("start", this.onUserMove);

    this.scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const sun = new THREE.DirectionalLight(0xffffff, 1.1);
    sun.position.set(-40, 90, 50);
    this.scene.add(sun);

    const count = (NX + 1) * (NZ + 1);
    this.heat = [new Float32Array(count), new Float32Array(count)];
    this.geometry = this.buildGeometry();
    const surface = new THREE.Mesh(this.geometry, new THREE.MeshStandardMaterial({
      vertexColors: true, roughness: 0.75, metalness: 0.05, side: THREE.DoubleSide,
    }));
    const lines = new THREE.Mesh(this.geometry, new THREE.MeshBasicMaterial({
      map: this.lineTexture(), transparent: true, depthWrite: false,
      polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
    }));
    this.scene.add(this.apron(), surface, lines);
    for (const end of [-1, 1]) {
      const goal = this.buildGoal(end);
      this.goals.push(goal);
      this.scene.add(goal);
    }

    this.ball = new THREE.Mesh(new THREE.SphereGeometry(0.9, 20, 16),
      new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 0.6 }));
    this.scene.add(this.ball);
    for (let n = 0; n < TRAIL; n++) {
      const dot = new THREE.Mesh(new THREE.CircleGeometry(1, 20), new THREE.MeshBasicMaterial({
        transparent: true, opacity: 0.85 * (1 - n / TRAIL), depthWrite: false, side: THREE.DoubleSide }));
      dot.rotation.x = -Math.PI / 2;
      dot.visible = false;
      this.trailDots.push(dot);
      this.scene.add(dot);
    }
    this.trailLine = new THREE.Line(new THREE.BufferGeometry().setAttribute("position",
      new THREE.BufferAttribute(new Float32Array(TRAIL * 3), 3)),
      new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.35, depthWrite: false }));
    this.trailLine.frustumCulled = false;
    this.scene.add(this.trailLine);

    this.clip = new ClipLayer((x, z) => this.heightAt(x + L / 2, W / 2 - z));
    this.scene.add(this.clip.group);
    this.context = new PlayerContextLayer((x, z) => this.heightAt(x + L / 2, W / 2 - z));
    this.scene.add(this.context.group);
    this.formation = new FormationLayer((x, z) => this.heightAt(x + L / 2, W / 2 - z));
    this.scene.add(this.formation.group);
    this.renderer.domElement.addEventListener("pointerdown", this.onPress);
    this.renderer.domElement.addEventListener("pointerup", this.onRelease);
    this.renderer.domElement.addEventListener("pointermove", this.onCameraDrag);
    this.renderer.domElement.addEventListener("wheel", this.onCameraWheel, { passive: true });
    this.renderer.domElement.addEventListener("dblclick", this.onResetView);

    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(container);
    this.resize();
    this.loop();
  }

  /** Use this match's team colours. Doesn't clear the surface: reset() does that, once per connection. */
  setMatch(meta: MatchMeta) {
    this.colours = teamColours(meta);
    this.homeId = meta.home.id;
    this.clip.setColours(this.colours[0], this.colours[1]);
    this.formation.setMatch(meta);
    this.dirty = true;
  }

  // ------------------------------------------------------------ the video clip

  /** Feed one `frame` of the tracked clip: everyone moves, and the territory surface follows where they were. */
  showFrame(frame: ClipFrame, meta: MatchMeta) {
    if (meta.home.id !== this.homeId) this.setMatch(meta);
    this.clip.push(frame, meta);
    const snapshot = this.context.history.push(frame, meta);
    const elapsed = this.lastFrameT === null ? 0 : Math.max(0, frame.t - this.lastFrameT);
    const dt = Math.min(1, elapsed);
    this.lastFrameT = frame.t;
    this.matchTime = frame.t;
    this.decay();
    const fade = Math.exp(-elapsed / CURRENT_TAU);
    for (const h of this.recentHeat) for (let k = 0; k < h.length; k++) h[k] *= fade;
    for (const h of this.instantHeat) h.fill(0);
    for (const p of snapshot.players.values()) {
      if (p.side === 2) continue;
      this.splat(p.side, p.x, p.y, CLIP_HEAT_PER_S * dt);
      this.stamp(this.recentHeat[p.side], p.x, p.y, 0.12 * dt, 4);
      this.stamp(this.instantHeat[p.side], p.x, p.y, 0.4, 4);
    }
    this.currentBall = snapshot.ball;
    this.dirty = true;
  }

  setSurfaceView(view: SurfaceView) {
    if (this.surfaceView === view) return;
    this.surfaceView = view;
    this.surface.reset();
    this.dirty = true;
  }

  setPlayerContext(options: PlayerContextOptions) { this.contextOptions = options; }

  setFormationOptions(enabled: boolean, team: FormationTeam) { this.formation.setOptions(enabled, team); }
  setOnFormationChange(callback: ((labels: FormationLabels) => void) | null) { this.formation.setOnChange(callback); }

  /** A detected event of the clip: a line (pass, carry) or ring (interception) that fades. */
  addClipEvent(ev: ClipEvent, meta: MatchMeta) {
    if (meta.home.id !== this.homeId) this.setMatch(meta);
    if (ev.type === "shot") {
      this.matchTime = Math.max(this.matchTime, ev.t);
      this.addShot(ev, meta, ev.t);
      return;
    }
    this.clip.addEvent(ev, meta);
  }

  /** The replay speed, which the drawing needs to move smoothly between frames. */
  setClipSpeed(speed: number) {
    this.clipSpeed = speed;
    if (this.cameraMode === "ball" || this.cameraMode === "player") this.setFollowOffset();
  }

  setOnCameraMode(fn: (mode: CameraMode) => void) { this.cameraModeChanged = fn; }

  setCameraMode(mode: CameraMode) {
    if (this.cameraMode === mode) return;
    this.cameraMode = mode;
    if (mode === "full") { this.onResetView(); return; }
    this.endFlight();
    this.userMoved = true;
    if (mode !== "manual") {
      this.setFollowOffset();
      this.controls.enableDamping = false;
    }
    this.cameraModeChanged?.(mode);
  }

  private setFollowOffset() {
    const fit = this.fittedView();
    this.followOffset.copy(fit.position).sub(fit.target).multiplyScalar(this.clipSpeed > 2 ? 0.95 : 0.82);
  }

  private onCameraWheel = () => this.setCameraMode("manual");
  private onCameraDrag = (event: PointerEvent) => {
    if (this.pressAt && Math.hypot(event.clientX - this.pressAt[0], event.clientY - this.pressAt[1]) > PICK_DRAG_PX)
      this.setCameraMode("manual");
  };

  /** Called with a tracked person's id when the viewer taps them on the pitch (to follow them with the spotlight). */
  setOnPick(fn: ((id: string) => void) | null) { this.onPick = fn; }

  private onPress = (e: PointerEvent) => { this.pressAt = [e.clientX, e.clientY]; };

  /** The controls' "start" (a press or a wheel turn), which comes before onPress. */
  private onUserMove = () => {
    this.movedBeforePress = this.userMoved;
    this.userMoved = true;
    this.endFlight();
  };

  /** Double-click: glide back to the default view, framed to fit. */
  private onResetView = () => {
    this.cameraMode = "full";
    this.cameraModeChanged?.("full");
    this.userMoved = false;
    this.flyTo = this.fittedView();
    this.controls.enableDamping = false; // drops any spin left over from the last drag, which would fight the glide
  };

  private endFlight() {
    this.flyTo = null;
    this.controls.enableDamping = true;
  }

  /** A tap (not a camera drag) on or near a tracked player picks them; a tap elsewhere does nothing. */
  private onRelease = (e: PointerEvent) => {
    const down = this.pressAt;
    this.pressAt = null;
    const tap = !!down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) <= PICK_DRAG_PX;
    if (tap) this.userMoved = this.movedBeforePress; // the controls call any press a move; a tap didn't move the camera
    if (!down || !tap || !this.clip.group.visible) return;
    const box = this.renderer.domElement.getBoundingClientRect();
    const id = this.clip.pick(e.clientX - box.left, e.clientY - box.top, this.camera, box.width, box.height);
    if (id) this.onPick?.(id);
  };

  /**
   * Follow a player with a ring and a beam, and keep `label` (an element over the pitch) beside them, or stop
   * (`null`). The label is a page element, not part of the 3D scene, so it stays sharp and can be held inside the
   * pitch when the player is at its edge. The events carry positions but there is no
   * tracking in the synthetic matches, so the spotlight sits where the player last took part (a pass, a carry,
   * a pass received, a tackle) and glides there; it stays hidden until the first such event, and while they are off.
   */
  setSpotlight(player: { id: string; colour: string } | null, label: HTMLElement | null = null) {
    if (this.spot && player && this.spot.id === player.id && this.spot.colour === player.colour) {
      if (this.spot.label !== label) {
        if (this.spot.label) this.spot.label.style.display = "none";
        this.spot.label = label;
        this.spot.labelSize = [0, 0];
      }
      return;
    }
    this.clearSpotlight(); // (another match can give the same player the other club's colour)
    if (!player) return;
    const colour = new THREE.Color(player.colour);
    const group = new THREE.Group();
    const flat = (inner: number, outer: number, opacity: number) => {
      const m = new THREE.Mesh(new THREE.RingGeometry(inner, outer, 56), new THREE.MeshBasicMaterial({
        color: colour, transparent: true, opacity, side: THREE.DoubleSide, depthWrite: false }));
      m.rotation.x = -Math.PI / 2;
      return m;
    };
    const ring = flat(2.1, 2.9, 0.95), pulse = flat(2.9, 3.4, 0.5);
    const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 2.6, 15, 28, 1, true), new THREE.MeshBasicMaterial({
      color: colour, transparent: true, opacity: 0.2, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending }));
    beam.position.y = 7.5;
    group.add(ring, pulse, beam);
    group.visible = false;
    this.scene.add(group);
    this.spot = { id: player.id, colour: player.colour, group, pulse, label, target: new THREE.Vector3(), placed: false, on: true,
                  labelSize: [0, 0] };
    this.placeSpotlight();
  }

  /** Show or hide the spotlight to match whether the player is on the pitch (from the live state). */
  setSpotlightOn(on: boolean) {
    if (this.spot) this.spot.on = on;
  }

  private clearSpotlight() {
    const spot = this.spot;
    if (!spot) return;
    this.scene.remove(spot.group);
    spot.group.traverse((obj) => {
      if (obj instanceof THREE.Mesh) { obj.geometry.dispose(); (obj.material as THREE.Material).dispose(); }
    });
    if (spot.label) spot.label.style.display = "none";
    this.spot = null;
  }

  /** Keep positions even before React attaches the selected player, including replay catch-up events. */
  private rememberPositions(ev: MatchEvent, meta: MatchMeta) {
    if (ev.player_id) {
      const at = (ev.type === "carry" ? toAbsolute(ev, meta, true) : null) ?? toAbsolute(ev, meta);
      if (at) this.playerPositions.set(ev.player_id, at);
    }
    if (ev.type === "pass" && typeof ev.receiver_id === "string" && ev.outcome === "complete") {
      const at = toAbsolute(ev, meta, true);
      if (at) this.playerPositions.set(ev.receiver_id, at);
    }
  }

  private placeSpotlight() {
    const spot = this.spot;
    const at = spot && this.playerPositions.get(spot.id);
    if (!spot || !at) return;
    spot.target.set(at[0] - L / 2, 0, W / 2 - at[1]);
    if (!spot.placed) { spot.group.position.copy(spot.target); spot.placed = true; }
  }

  /** Catch-up positions can be older than the heat map. Restore them without adding old heat or moving the ball. */
  restorePlayerPositions(events: MatchEvent[], meta: MatchMeta) {
    for (const ev of events) this.rememberPositions(ev, meta);
    this.placeSpotlight();
  }

  reset() {
    this.playerPositions.clear();
    if (this.spot) { this.spot.placed = false; this.spot.on = true; this.spot.group.visible = false; }
    this.clip.clear();
    this.context.clear();
    this.formation.clear();
    for (const h of [...this.recentHeat, ...this.instantHeat]) h.fill(0);
    this.currentBall = null;
    this.touches = [];
    this.lastFrameT = null;
    this.heat[0].fill(0);
    this.heat[1].fill(0);
    this.spikes = [];
    this.surface.reset();
    // A seek must remove old hills immediately, including while paused.
    const position = this.geometry.getAttribute("position") as THREE.BufferAttribute;
    const normal = this.geometry.getAttribute("normal") as THREE.BufferAttribute;
    const colour = this.geometry.getAttribute("color") as THREE.BufferAttribute;
    for (let k = 0; k < position.count; k++) {
      position.setY(k, 0);
      normal.setXYZ(k, 0, 1, 0);
      colour.setXYZ(k, BASE_COLOUR.r, BASE_COLOUR.g, BASE_COLOUR.b);
    }
    position.needsUpdate = normal.needsUpdate = colour.needsUpdate = true;
    this.matchTime = 0;
    this.lastDecayTime = 0;
    this.dirty = true;
  }

  /** Feed one event from the stream. */
  addEvent(ev: MatchEvent, meta: MatchMeta, matchTime: number) {
    // Events can arrive before React has passed the new match in, so take the teams from the event's meta.
    if (meta.home.id !== this.homeId) this.setMatch(meta);
    this.matchTime = matchTime;
    this.decay();
    this.rememberPositions(ev, meta);
    if (this.spot) {
      if (ev.type === "substitution" && ev.player_off_id === this.spot.id) this.spot.on = false;
      else if (ev.type === "foul" && ev.card === "red" && ev.player_id === this.spot.id) this.spot.on = false;
      else if (ev.type === "substitution" && ev.player_on_id === this.spot.id) this.spot.on = true;
      this.placeSpotlight();
    }
    const pos = toAbsolute(ev, meta);
    if (!pos || !ev.team_id) return;
    const side = ev.team_id === this.homeId ? 0 : 1;
    const weight = ev.type === "shot" ? 0.9 : ev.type === "pressure" ? 0.12 : ev.type === "pass" ? 0.2 : 0.25;
    this.splat(side, pos[0], pos[1], weight);
    const end = toAbsolute(ev, meta, true);
    if (ev.type !== "pressure" && ev.type !== "foul") this.touch(side, pos[0], pos[1]); // near the ball, not touches of it
    if (end && (ev.type === "carry" || (ev.type === "pass" && ev.outcome === "complete"))) {
      this.splat(side, end[0], end[1], 0.15);
      this.moveBall(end[0], end[1]);
      if (ev.type === "pass") this.touch(side, end[0], end[1]);
    } else {
      this.moveBall(pos[0], pos[1]);
    }
    if (ev.type === "shot") {
      this.addShot(ev, meta, matchTime);
    }
    this.dirty = true;
  }

  private addShot(ev: MatchEvent, meta: MatchMeta, matchTime: number) {
    const pos = toAbsolute(ev, meta);
    if (!pos) return;
    const goal = ev.outcome === "goal";
    this.spikes.push({ x: pos[0], y: pos[1], amp: 4 + (ev.xg ?? 0.05) * 12 + (goal ? 3 : 0), born: matchTime, goal });
    this.dirty = true;
  }

  dispose() {
    cancelAnimationFrame(this.frame);
    this.clearSpotlight();
    this.renderer.domElement.removeEventListener("pointerdown", this.onPress);
    this.renderer.domElement.removeEventListener("pointerup", this.onRelease);
    this.renderer.domElement.removeEventListener("pointermove", this.onCameraDrag);
    this.renderer.domElement.removeEventListener("wheel", this.onCameraWheel);
    this.renderer.domElement.removeEventListener("dblclick", this.onResetView);
    this.controls.removeEventListener("start", this.onUserMove);
    this.clip.dispose();
    this.scene.remove(this.context.group);
    this.context.dispose();
    this.scene.remove(this.formation.group);
    this.formation.dispose();
    this.observer.disconnect();
    this.controls.dispose();
    this.scene.traverse((obj) => {
      if (!(obj instanceof THREE.Mesh || obj instanceof THREE.Line)) return; // (LineSegments is a Line)
      obj.geometry.dispose();
      for (const m of Array.isArray(obj.material) ? obj.material : [obj.material]) {
        (m as THREE.MeshBasicMaterial).map?.dispose();
        m.dispose();
      }
    });
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }

  // ------------------------------------------------------------ internals

  private idx(i: number, j: number) { return j * (NX + 1) + i; }

  /** A dark ground under the pitch that fades out, so the surface sits on something rather than floating. */
  private apron() {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 128;
    const c = canvas.getContext("2d")!;
    const g = c.createRadialGradient(64, 64, 20, 64, 64, 64);
    g.addColorStop(0, "rgba(7,14,20,0.9)");
    g.addColorStop(0.7, "rgba(7,14,20,0.55)");
    g.addColorStop(1, "rgba(7,14,20,0)");
    c.fillStyle = g;
    c.fillRect(0, 0, 128, 128);
    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(L * 1.5, W * 1.9), new THREE.MeshBasicMaterial({
      map: tex, transparent: true, depthWrite: false }));
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.y = -0.3;
    mesh.renderOrder = -1;
    return mesh;
  }

  /** A goal frame and net at one end (-1 left, 1 right), opening onto the pitch. It rides the surface's height. */
  private buildGoal(end: number) {
    const group = new THREE.Group();
    const frame = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 0.4 });
    const t = 0.3; // thicker than a real post (0.12 m) so it reads at this distance
    for (const z of [-GOAL_W / 2, GOAL_W / 2]) {
      const post = new THREE.Mesh(new THREE.BoxGeometry(t, GOAL_H, t), frame);
      post.position.set(0, GOAL_H / 2, z);
      group.add(post);
    }
    const bar = new THREE.Mesh(new THREE.BoxGeometry(t, t, GOAL_W + t), frame);
    bar.position.set(0, GOAL_H, 0);
    group.add(bar);
    // The net: a faint box behind the goal line, with its edges drawn.
    const net = new THREE.BoxGeometry(GOAL_D, GOAL_H, GOAL_W);
    net.translate(GOAL_D / 2, GOAL_H / 2, 0);
    group.add(new THREE.Mesh(net, new THREE.MeshBasicMaterial({
      color: 0xffffff, transparent: true, opacity: 0.1, side: THREE.DoubleSide, depthWrite: false })));
    group.add(new THREE.LineSegments(new THREE.EdgesGeometry(net), new THREE.LineBasicMaterial({
      color: 0xffffff, transparent: true, opacity: 0.35, depthWrite: false })));
    group.position.x = (end * L) / 2;
    if (end < 0) group.rotation.y = Math.PI; // the net goes behind the goal line, away from the pitch
    return group;
  }

  /**
   * The default view for the pitch's current size: centred, the whole pitch and its goals in frame. A portrait box
   * (a phone) looks down the pitch's length instead of across it, so the pitch fills the height.
   */
  private fittedView() {
    const cam = this.camera.clone();
    const target = new THREE.Vector3();
    const az = this.camera.aspect < 0.9 ? Math.PI / 2 : 0;
    const flat = new THREE.Vector3(Math.sin(az), 0, Math.cos(az)); // from the pitch towards the camera, along the ground
    const dir = flat.clone().multiplyScalar(Math.cos(VIEW_ELEVATION)).setY(Math.sin(VIEW_ELEVATION));
    const corners: THREE.Vector3[] = [];
    for (const x of [-L / 2 - GOAL_D, L / 2 + GOAL_D]) {
      for (const z of [-W / 2, W / 2]) for (const y of [0, 5]) corners.push(new THREE.Vector3(x, y, z));
    }
    const v = new THREE.Vector3();
    let d = 120;
    for (let n = 0; n < 8; n++) {
      cam.position.copy(target).addScaledVector(dir, d);
      cam.lookAt(target);
      cam.updateMatrixWorld();
      let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
      for (const p of corners) {
        v.copy(p).project(cam);
        x0 = Math.min(x0, v.x); x1 = Math.max(x1, v.x); y0 = Math.min(y0, v.y); y1 = Math.max(y1, v.y);
      }
      // Centre the pitch vertically (moving the target towards the far side moves the pitch down the screen)...
      target.addScaledVector(flat, -((y0 + y1) / 2) * d * Math.tan((cam.fov * Math.PI) / 360) / Math.sin(VIEW_ELEVATION));
      // ...and stand back just far enough to fit it, with a margin.
      d *= Math.max((x1 - x0) / 2 / 0.94, (y1 - y0) / 2 / 0.86);
    }
    return { position: target.clone().addScaledVector(dir, d), target };
  }

  private frameView(view = this.fittedView()) {
    this.controls.maxDistance = Math.max(220, view.position.distanceTo(view.target) * 1.5);
    this.camera.position.copy(view.position);
    this.controls.target.copy(view.target);
    this.endFlight();
  }

  /** Remember where the ball was touched, for the trail. */
  private touch(side: number, x: number, y: number) {
    const last = this.touches[0];
    if (last && last.side === side && Math.hypot(last.x - x, last.y - y) < 1) return; // (a pass's end is the next carry's start)
    this.touches.unshift({ x, y, side });
    if (this.touches.length > TRAIL) this.touches.length = TRAIL;
  }

  /** The last few touches as dots in the toucher's colour, joined by a line, fading with age. */
  private drawTrail() {
    const show = !this.clip.group.visible;
    const line = this.trailLine.geometry.getAttribute("position") as THREE.BufferAttribute;
    for (let n = 0; n < TRAIL; n++) {
      const dot = this.trailDots[n];
      const t = this.touches[n];
      dot.visible = show && !!t;
      if (!t) continue;
      // Above the highest point around it, so a dot on a slope (a shot's spike) isn't buried in it.
      let y = -Infinity;
      for (const [dx, dy] of [[0, 0], [-1, 0], [1, 0], [0, -1], [0, 1]]) y = Math.max(y, this.heightAt(t.x + dx, t.y + dy));
      y += 0.25;
      const x = t.x - L / 2, z = W / 2 - t.y;
      dot.position.set(x, y, z);
      (dot.material as THREE.MeshBasicMaterial).color.copy(this.colours[t.side]);
      line.setXYZ(n, x, y + 0.05, z);
    }
    this.trailLine.visible = show && this.touches.length > 1;
    this.trailLine.geometry.setDrawRange(0, this.touches.length);
    line.needsUpdate = true;
  }

  private placeGoals() {
    for (const goal of this.goals) {
      const y = this.heightAt(goal.position.x + L / 2, W / 2);
      goal.position.y += (y - goal.position.y) * 0.15;
    }
  }

  private buildGeometry() {
    const g = new THREE.BufferGeometry();
    const count = (NX + 1) * (NZ + 1);
    const pos = new Float32Array(count * 3);
    const uv = new Float32Array(count * 2);
    const col = new Float32Array(count * 3);
    for (let j = 0; j <= NZ; j++) {
      for (let i = 0; i <= NX; i++) {
        const k = this.idx(i, j);
        pos[k * 3] = (i / NX) * L - L / 2;
        pos[k * 3 + 2] = W / 2 - (j / NZ) * W;
        uv[k * 2] = i / NX;
        uv[k * 2 + 1] = j / NZ;
      }
    }
    const index: number[] = [];
    for (let j = 0; j < NZ; j++) {
      for (let i = 0; i < NX; i++) {
        const a = this.idx(i, j), b = this.idx(i + 1, j), c = this.idx(i, j + 1), d = this.idx(i + 1, j + 1);
        index.push(a, b, c, b, d, c); // counter-clockwise seen from above, so faces (and normals) point up
      }
    }
    g.setIndex(index);
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
    g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    g.computeVertexNormals();
    return g;
  }

  private lineTexture() {
    const s = 20; // pixels per metre
    const canvas = document.createElement("canvas");
    canvas.width = L * s;
    canvas.height = W * s;
    const c = canvas.getContext("2d")!;
    c.strokeStyle = "rgba(255,255,255,0.95)";
    c.lineWidth = 0.4 * s; // wider than real lines so they survive texture filtering at a low viewing angle
    // Canvas y runs down while pitch y (uv v) runs up, so flip.
    const P = (x: number, y: number): [number, number] => [x * s, (W - y) * s];
    const rect = (x: number, y: number, w: number, h: number) => {
      const [px, py] = P(x, y + h);
      c.strokeRect(px, py, w * s, h * s);
    };
    rect(0.2, 0.2, L - 0.4, W - 0.4);
    c.beginPath(); c.moveTo(...P(L / 2, 0)); c.lineTo(...P(L / 2, W)); c.stroke();
    c.beginPath(); c.arc(...P(L / 2, W / 2), 9.15 * s, 0, Math.PI * 2); c.stroke();
    for (const left of [true, false]) {
      const x0 = left ? 0 : L;
      const dir = left ? 1 : -1;
      rect(left ? 0 : L - 16.5, W / 2 - 20.16, 16.5, 40.32);
      rect(left ? 0 : L - 5.5, W / 2 - 9.16, 5.5, 18.32);
      c.beginPath();
      const [sx, sy] = P(x0 + dir * 11, W / 2);
      c.arc(sx, sy, 0.45 * s, 0, Math.PI * 2);
      c.fillStyle = "rgba(255,255,255,0.95)";
      c.fill();
      c.beginPath();
      const a = Math.acos(5.5 / 9.15);
      if (left) c.arc(sx, sy, 9.15 * s, -a, a);
      else c.arc(sx, sy, 9.15 * s, Math.PI - a, Math.PI + a);
      c.stroke();
    }
    const tex = new THREE.CanvasTexture(canvas);
    tex.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
    tex.colorSpace = THREE.SRGBColorSpace;
    return tex;
  }

  private splat(side: number, x: number, y: number, amount: number) {
    this.stamp(this.heat[side], x, y, amount, SIGMA);
  }

  private stamp(h: Float32Array, x: number, y: number, amount: number, sigma: number) {
    const r = Math.ceil(sigma * 2.5);
    const ci = Math.round((x / L) * NX), cj = Math.round((y / W) * NZ);
    for (let j = Math.max(0, cj - r); j <= Math.min(NZ, cj + r); j++) {
      for (let i = Math.max(0, ci - r); i <= Math.min(NX, ci + r); i++) {
        const dx = (i / NX) * L - x, dy = (j / NZ) * W - y;
        h[this.idx(i, j)] += amount * Math.exp(-(dx * dx + dy * dy) / (2 * sigma * sigma));
      }
    }
  }

  private decay() {
    const dt = this.matchTime - this.lastDecayTime;
    if (dt <= 0) return;
    const f = Math.exp(-dt / TERRITORY_TAU);
    for (const h of this.heat) for (let k = 0; k < h.length; k++) h[k] *= f;
    this.lastDecayTime = this.matchTime;
    this.spikes = this.spikes.filter((s) => this.matchTime - s.born < SPIKE_TAU * 4);
  }

  private moveBall(x: number, y: number) {
    this.ballTarget.set(x - L / 2, 0, W / 2 - y);
  }

  private heightAt(x: number, y: number) {
    const gx = Math.min(NX, Math.max(0, (x / L) * NX)), gy = Math.min(NZ, Math.max(0, (y / W) * NZ));
    const i = Math.min(NX - 1, Math.floor(gx)), j = Math.min(NZ - 1, Math.floor(gy));
    const u = gx - i, v = gy - j;
    const pos = this.geometry.getAttribute("position") as THREE.BufferAttribute;
    const a = pos.getY(this.idx(i, j)), b = pos.getY(this.idx(i + 1, j));
    const c = pos.getY(this.idx(i, j + 1)), d = pos.getY(this.idx(i + 1, j + 1));
    return (a + (b - a) * u) * (1 - v) + (c + (d - c) * u) * v;
  }

  private updateSurface(now: number) {
    const [ch, ca] = this.colours;
    const tmp = this.tmpColour;
    const spikes = this.spikes;
    const current = this.clip.group.visible && this.surfaceView === "current";
    const amps = spikes.map((s) => {
      const age = Math.max(0, this.matchTime - s.born);
      // Sparse event feeds need an immediate target; tracked feeds have frames throughout the rise.
      const rise = this.clip.group.visible ? 1 - Math.exp(-age / SPIKE_RISE_S) : 1;
      return s.amp * rise * Math.exp(-age / SPIKE_TAU);
    });
    for (let j = 0; j <= NZ; j++) {
      for (let i = 0; i <= NX; i++) {
        const k = this.idx(i, j);
        const hh = current ? this.recentHeat[0][k] + this.instantHeat[0][k] : this.heat[0][k];
        const ha = current ? this.recentHeat[1][k] + this.instantHeat[1][k] : this.heat[1][k];
        const total = hh + ha;
        let height = 9 * Math.tanh(total / 3);
        const x = (i / NX) * L, y = (j / NZ) * W;
        let glow = 0;
        const ballInfluence = current && this.currentBall ? Math.exp(-((x - this.currentBall.x) ** 2 + (y - this.currentBall.y) ** 2) / 50) : 0;
        height += 1.8 * ballInfluence;
        for (let n = 0; n < spikes.length; n++) {
          const s = spikes[n];
          const d2 = (x - s.x) ** 2 + (y - s.y) ** 2;
          const v = amps[n] * Math.exp(-d2 / (2 * 2.2 * 2.2));
          height += v;
          if (s.goal) glow = Math.max(glow, Math.min(1, v / 5) * Math.exp(-Math.max(0, this.matchTime - s.born) / GOAL_GLOW_TAU));
        }
        this.surfaceHeights[k] = height;
        const raw = total > 1e-4 ? hh / total : 0.5;
        // Who owns this space, from -1 (away) to 1 (home), sharpened smoothly so ownership reads without hard edges.
        // Shared space fades to slate rather than mixing the colours, which turned a red and a blue team's pitch purple.
        const lead = Math.tanh((raw - 0.5) * 4);
        tmp.copy(CONTESTED_COLOUR).lerp(lead >= 0 ? ch : ca, Math.min(1, Math.abs(lead) * 1.2));
        const strength = Math.min(1, total / 1.5);
        const visibility = current ? 1 - Math.exp(-total * 1.7) : 0.3 + 0.7 * strength;
        tmp.lerp(BASE_COLOUR, 1 - visibility);
        if (ballInfluence) tmp.lerp(GLOW_COLOUR, ballInfluence * 0.15);
        if (glow > 0) tmp.lerp(GLOW_COLOUR, glow * 0.8);
        this.surfaceColours[k * 3] = tmp.r;
        this.surfaceColours[k * 3 + 1] = tmp.g;
        this.surfaceColours[k * 3 + 2] = tmp.b;
      }
    }
    if (this.clip.group.visible) this.surface.push(this.matchTime, this.surfaceHeights, this.surfaceColours);
    else this.surface.transition(now / 1000, 0.18, this.surfaceHeights, this.surfaceColours);
  }

  private drawSurface(t: number) {
    if (!this.surface.sample(t)) return;
    const pos = this.geometry.getAttribute("position") as THREE.BufferAttribute;
    const col = this.geometry.getAttribute("color") as THREE.BufferAttribute;
    const normals = this.geometry.getAttribute("normal") as THREE.BufferAttribute;
    const heights = this.surface.heights;
    for (let j = 0; j <= NZ; j++) for (let i = 0; i <= NX; i++) {
      const k = this.idx(i, j);
      pos.setY(k, heights[k]);
      // Smooth grid gradients avoid rebuilding every triangle's normals on every draw.
      const left = Math.max(0, i - 1), right = Math.min(NX, i + 1);
      const top = Math.max(0, j - 1), bottom = Math.min(NZ, j + 1);
      const dx = (heights[this.idx(right, j)] - heights[this.idx(left, j)]) / ((right - left) * L / NX);
      const dy = (heights[this.idx(i, bottom)] - heights[this.idx(i, top)]) / ((bottom - top) * W / NZ);
      const length = Math.hypot(dx, 1, dy);
      normals.setXYZ(k, -dx / length, 1 / length, dy / length);
    }
    (col.array as Float32Array).set(this.surface.colours);
    pos.needsUpdate = col.needsUpdate = normals.needsUpdate = true;
  }

  private drawTrackedSurface = (t: number) => this.drawSurface(t);

  private resize() {
    const { clientWidth: w, clientHeight: h } = this.container;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    if (this.cameraMode === "ball" || this.cameraMode === "player") this.setFollowOffset();
    if (!this.userMoved) this.frameView();
  }

  private moveSpotlight() {
    const spot = this.spot;
    if (!spot) return;
    const tracked = this.clip.group.visible;
    if (tracked) { // a clip: follow the person's tracked position, frame by frame, while the tracker has them
      const at = this.clip.positionOf(spot.id);
      spot.on = !!at;
      if (at) {
        spot.target.set(at.x, 0, at.z);
        if (!spot.placed) { spot.group.position.copy(spot.target); spot.placed = true; }
      }
    }
    spot.group.visible = spot.placed && spot.on;
    if (spot.label) spot.label.style.display = spot.group.visible ? "block" : "none";
    if (!spot.group.visible) return;
    const g = spot.group.position;
    const x = spot.target.x, z = spot.target.z;
    const k = tracked ? 0.35 : 0.1; // a tracked position is already smooth: just take the edge off
    g.set(g.x + (x - g.x) * k, 0, g.z + (z - g.z) * k);
    g.y = this.heightAt(g.x + L / 2, W / 2 - g.z) + 0.5;
    const beat = (performance.now() % 1600) / 1600; // a ring that swells and fades, once every 1.6 s
    spot.pulse.scale.setScalar(1 + beat * 0.9);
    (spot.pulse.material as THREE.MeshBasicMaterial).opacity = 0.55 * (1 - beat);
    if (spot.label) this.placeLabel(spot.label, g);
  }

  /** Put the label above the player's beam, inside the pitch's box. */
  private placeLabel(label: HTMLElement, at: THREE.Vector3) {
    const { clientWidth: cw, clientHeight: ch } = this.container;
    const v = this.tmpVector.set(at.x, at.y + 10, at.z).project(this.camera);
    const spot = this.spot!;
    if (!spot.labelSize[0]) spot.labelSize = [label.offsetWidth, label.offsetHeight]; // measured once: reading it every frame forces a layout
    const [w, h] = spot.labelSize;
    const x = Math.min(cw - w - 6, Math.max(6, (v.x * 0.5 + 0.5) * cw - w / 2));
    const y = Math.min(ch - h - 6, Math.max(6, (-v.y * 0.5 + 0.5) * ch - h));
    label.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
  }

  private loop = () => {
    this.frame = requestAnimationFrame(this.loop);
    const now = performance.now();
    if (this.dirty) {
      this.updateSurface(now);
      this.dirty = false;
    }
    if (this.clip.group.visible) this.clip.update(this.clipSpeed, now, this.drawTrackedSurface);
    else this.drawSurface(now / 1000);
    if (this.clip.group.visible) this.context.update(this.clip.drawnTime, this.spot?.id ?? null,
      this.clip.playersNow(), this.colours, this.contextOptions);
    if (this.clip.group.visible) this.formation.update(this.clip.drawnTime, this.clip.playersNow(), this.colours,
      this.clip.drawnPeriod, this.clip.drawnPhase);
    const bx = this.ballTarget.x + L / 2, by = W / 2 - this.ballTarget.z;
    const target = new THREE.Vector3(this.ballTarget.x, this.heightAt(bx, by) + 1.4, this.ballTarget.z);
    this.ball.position.lerp(target, 0.18);
    this.ball.visible = !this.clip.group.visible; // a clip draws its own ball, only where the video found it
    this.moveSpotlight();
    const focus = cameraFocus(this.cameraMode, this.clip.ballNow(), this.spot ? this.clip.positionOf(this.spot.id) : undefined);
    const blend = cameraBlend(this.lastCameraAt === null ? 0 : (now - this.lastCameraAt) / 1000);
    this.lastCameraAt = now;
    if (focus) {
      this.followTarget.set(focus.x, this.heightAt(focus.x + L / 2, W / 2 - focus.z) * 0.3, focus.z);
      this.controls.target.lerp(this.followTarget, blend);
      this.tmpVector.copy(this.followTarget).add(this.followOffset);
      this.camera.position.lerp(this.tmpVector, blend);
    }
    this.placeGoals();
    this.drawTrail();
    if (this.flyTo) {
      this.camera.position.lerp(this.flyTo.position, 0.12);
      this.controls.target.lerp(this.flyTo.target, 0.12);
      if (this.camera.position.distanceTo(this.flyTo.position) < 0.2) this.frameView(this.flyTo); // land exactly
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  };
}
