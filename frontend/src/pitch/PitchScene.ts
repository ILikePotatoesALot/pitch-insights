import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { ClipEvent, ClipFrame, MatchEvent, MatchMeta } from "../types";
import { ClipLayer } from "./ClipLayer";

const L = 105;
const W = 68;
const NX = 105; // grid cells along the length (1 m each)
const NZ = 68;
const TERRITORY_TAU = 120; // seconds of match time for activity to fade to ~37%
const SPIKE_TAU = 75;
const SIGMA = 7; // metres: how far one action's influence spreads
const CLIP_HEAT_PER_S = 0.015; // territory a tracked player adds each second, at their spot (an event adds 0.2 to 0.9)
const PICK_DRAG_PX = 5; // a press that moves further than this is a camera drag, not a tap on a player

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
const GLOW_COLOUR = new THREE.Color("#fff6c2");

export class PitchScene {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private controls: OrbitControls;
  private geometry: THREE.BufferGeometry;
  private heat: [Float32Array, Float32Array];
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
  private tmpColour = new THREE.Color();
  private spot: Spotlight | null = null;
  private tmpVector = new THREE.Vector3();
  private clip: ClipLayer;
  private clipSpeed = 1;
  private clipLabel: HTMLElement | null = null;
  private clipLabelText = "";
  private clipLabelSize: [number, number] = [0, 0];
  private lastFrameT: number | null = null;
  private pressAt: [number, number] | null = null;

  constructor(private container: HTMLElement) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(this.renderer.domElement);

    this.camera = new THREE.PerspectiveCamera(38, 1, 1, 1000);
    this.camera.position.set(-18, 72, 92);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(0, 0, 0);
    this.controls.enableDamping = true;
    this.controls.maxPolarAngle = Math.PI * 0.45;
    this.controls.minDistance = 40;
    this.controls.maxDistance = 220;

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
    this.scene.add(surface, lines);

    this.ball = new THREE.Mesh(new THREE.SphereGeometry(0.9, 20, 16),
      new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 0.6 }));
    this.scene.add(this.ball);

    this.clip = new ClipLayer((x, z) => this.heightAt(x + L / 2, W / 2 - z));
    this.scene.add(this.clip.group);
    this.renderer.domElement.addEventListener("pointerdown", this.onPress);
    this.renderer.domElement.addEventListener("pointerup", this.onRelease);

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
    this.dirty = true;
  }

  // ------------------------------------------------------------ the video clip

  /** Feed one `frame` of the tracked clip: everyone moves, and the territory surface follows where they were. */
  showFrame(frame: ClipFrame, meta: MatchMeta) {
    if (meta.home.id !== this.homeId) this.setMatch(meta);
    this.clip.push(frame, meta);
    const dt = this.lastFrameT === null ? 0 : Math.min(1, Math.max(0, frame.t - this.lastFrameT));
    this.lastFrameT = frame.t;
    this.matchTime = frame.t;
    this.decay();
    for (const p of this.clip.lastPlayers()) this.splat(p.side, p.x, p.y, CLIP_HEAT_PER_S * dt);
    this.dirty = true;
  }

  /** A detected event of the clip: a line (pass, carry) or ring (interception) that fades. */
  addClipEvent(ev: ClipEvent, meta: MatchMeta) {
    if (meta.home.id !== this.homeId) this.setMatch(meta);
    this.clip.addEvent(ev, meta);
  }

  /** The replay speed, which the drawing needs to move smoothly between frames. */
  setClipSpeed(speed: number) { this.clipSpeed = speed; }

  /** The page element for the label of the player the viewer tapped (kept beside them, like the spotlight's). */
  setClipLabel(el: HTMLElement | null) { this.clipLabel = el; }

  private onPress = (e: PointerEvent) => { this.pressAt = [e.clientX, e.clientY]; };

  /** A tap (not a camera drag) on or near a tracked player selects them; a tap elsewhere clears it. */
  private onRelease = (e: PointerEvent) => {
    const down = this.pressAt;
    this.pressAt = null;
    if (!down || !this.clip.group.visible || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > PICK_DRAG_PX) return;
    const box = this.renderer.domElement.getBoundingClientRect();
    this.clip.select(this.clip.pick(e.clientX - box.left, e.clientY - box.top, this.camera, box.width, box.height));
  };

  private placeClipLabel() {
    const label = this.clipLabel;
    if (!label) return;
    const { clientWidth: cw, clientHeight: ch } = this.container;
    const info = this.clip.group.visible ? this.clip.selectedInfo(this.camera, cw, ch) : null;
    label.style.display = info ? "block" : "none";
    if (!info) return;
    if (info.text !== this.clipLabelText) {
      label.textContent = info.text;
      this.clipLabelText = info.text;
      this.clipLabelSize = [label.offsetWidth, label.offsetHeight]; // measured when the text changes, not every frame
    }
    const [w, h] = this.clipLabelSize;
    const x = Math.min(cw - w - 6, Math.max(6, info.x - w / 2));
    const y = Math.min(ch - h - 6, Math.max(6, info.y - h));
    label.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
  }

  /**
   * Follow a player with a ring and a beam, and keep `label` (an element over the pitch) beside them, or stop
   * (`null`). The label is a page element, not part of the 3D scene, so it stays sharp and can be held inside the
   * pitch when the player is at its edge. The events carry positions but there is no
   * tracking in the synthetic matches, so the spotlight sits where the player last took part (a pass, a carry,
   * a pass received, a tackle) and glides there; it stays hidden until the first such event, and while they are off.
   */
  setSpotlight(player: { id: string; colour: string } | null, label: HTMLElement | null = null) {
    if (this.spot && player && this.spot.id === player.id && this.spot.colour === player.colour) return;
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

  /** Where this event puts the spotlit player, in pitch metres, or null if it says nothing about them. */
  private spotPosition(ev: MatchEvent, meta: MatchMeta): [number, number] | null {
    const id = this.spot?.id;
    if (ev.player_id === id) {
      return (ev.type === "carry" ? toAbsolute(ev, meta, true) : null) ?? toAbsolute(ev, meta);
    }
    if (ev.type === "pass" && ev.receiver_id === id && ev.outcome === "complete") return toAbsolute(ev, meta, true);
    return null;
  }

  reset() {
    if (this.spot) { this.spot.placed = false; this.spot.on = true; this.spot.group.visible = false; }
    this.clip.clear();
    this.lastFrameT = null;
    if (this.clipLabel) this.clipLabel.style.display = "none";
    this.heat[0].fill(0);
    this.heat[1].fill(0);
    this.spikes = [];
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
    if (this.spot) {
      if (ev.type === "substitution" && ev.player_off_id === this.spot.id) this.spot.on = false;
      else if (ev.type === "foul" && ev.card === "red" && ev.player_id === this.spot.id) this.spot.on = false;
      else if (ev.type === "substitution" && ev.player_on_id === this.spot.id) this.spot.on = true;
      const at = this.spotPosition(ev, meta);
      if (at) {
        this.spot.target.set(at[0] - L / 2, 0, W / 2 - at[1]);
        if (!this.spot.placed) { this.spot.group.position.copy(this.spot.target); this.spot.placed = true; }
      }
    }
    const pos = toAbsolute(ev, meta);
    if (!pos || !ev.team_id) return;
    const side = ev.team_id === this.homeId ? 0 : 1;
    const weight = ev.type === "shot" ? 0.9 : ev.type === "pressure" ? 0.12 : ev.type === "pass" ? 0.2 : 0.25;
    this.splat(side, pos[0], pos[1], weight);
    const end = toAbsolute(ev, meta, true);
    if (end && (ev.type === "carry" || (ev.type === "pass" && ev.outcome === "complete"))) {
      this.splat(side, end[0], end[1], 0.15);
      this.moveBall(end[0], end[1]);
    } else {
      this.moveBall(pos[0], pos[1]);
    }
    if (ev.type === "shot") {
      const goal = ev.outcome === "goal";
      this.spikes.push({ x: pos[0], y: pos[1], amp: 6 + (ev.xg ?? 0.05) * 55 + (goal ? 10 : 0), born: matchTime, goal });
    }
    this.dirty = true;
  }

  dispose() {
    cancelAnimationFrame(this.frame);
    this.clearSpotlight();
    this.renderer.domElement.removeEventListener("pointerdown", this.onPress);
    this.renderer.domElement.removeEventListener("pointerup", this.onRelease);
    this.clip.dispose();
    this.observer.disconnect();
    this.controls.dispose();
    this.scene.traverse((obj) => {
      if (!(obj instanceof THREE.Mesh)) return;
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
    const h = this.heat[side];
    const r = Math.ceil(SIGMA * 2.5);
    const ci = Math.round((x / L) * NX), cj = Math.round((y / W) * NZ);
    for (let j = Math.max(0, cj - r); j <= Math.min(NZ, cj + r); j++) {
      for (let i = Math.max(0, ci - r); i <= Math.min(NX, ci + r); i++) {
        const dx = (i / NX) * L - x, dy = (j / NZ) * W - y;
        h[this.idx(i, j)] += amount * Math.exp(-(dx * dx + dy * dy) / (2 * SIGMA * SIGMA));
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
    const i = Math.min(NX, Math.max(0, Math.round((x / L) * NX)));
    const j = Math.min(NZ, Math.max(0, Math.round((y / W) * NZ)));
    return (this.geometry.getAttribute("position") as THREE.BufferAttribute).getY(this.idx(i, j));
  }

  private updateSurface() {
    const pos = this.geometry.getAttribute("position") as THREE.BufferAttribute;
    const col = this.geometry.getAttribute("color") as THREE.BufferAttribute;
    const [ch, ca] = this.colours;
    const tmp = this.tmpColour;
    const spikes = this.spikes;
    const amps = spikes.map((s) => s.amp * Math.exp(-(this.matchTime - s.born) / SPIKE_TAU));
    for (let j = 0; j <= NZ; j++) {
      for (let i = 0; i <= NX; i++) {
        const k = this.idx(i, j);
        const hh = this.heat[0][k], ha = this.heat[1][k];
        const total = hh + ha;
        let height = 9 * Math.tanh(total / 3);
        const x = (i / NX) * L, y = (j / NZ) * W;
        let glow = 0;
        for (let n = 0; n < spikes.length; n++) {
          const s = spikes[n];
          const d2 = (x - s.x) ** 2 + (y - s.y) ** 2;
          const v = amps[n] * Math.exp(-d2 / (2 * 2.2 * 2.2));
          height += v;
          if (s.goal) glow = Math.max(glow, Math.min(1, v / 8));
        }
        pos.setY(k, height);
        const raw = total > 1e-4 ? hh / total : 0.5;
        const share = 0.5 + 0.5 * Math.tanh((raw - 0.5) * 3); // sharpen smoothly, so ownership reads clearly without hard edges
        tmp.copy(ca).lerp(ch, share);
        const strength = Math.min(1, total / 1.5);
        tmp.lerp(BASE_COLOUR, 1 - (0.25 + 0.75 * strength));
        if (glow > 0) tmp.lerp(GLOW_COLOUR, glow * 0.8);
        col.setXYZ(k, tmp.r, tmp.g, tmp.b);
      }
    }
    pos.needsUpdate = true;
    col.needsUpdate = true;
    this.geometry.computeVertexNormals();
  }

  private resize() {
    const { clientWidth: w, clientHeight: h } = this.container;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  private moveSpotlight() {
    const spot = this.spot;
    if (!spot) return;
    spot.group.visible = spot.placed && spot.on;
    if (spot.label) spot.label.style.display = spot.group.visible ? "block" : "none";
    if (!spot.group.visible) return;
    const g = spot.group.position;
    const x = spot.target.x, z = spot.target.z;
    g.set(g.x + (x - g.x) * 0.1, 0, g.z + (z - g.z) * 0.1);
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
    if (this.dirty) {
      this.updateSurface();
      this.dirty = false;
    }
    const bx = this.ballTarget.x + L / 2, by = W / 2 - this.ballTarget.z;
    const target = new THREE.Vector3(this.ballTarget.x, this.heightAt(bx, by) + 1.4, this.ballTarget.z);
    this.ball.position.lerp(target, 0.18);
    this.ball.visible = !this.clip.group.visible; // a clip draws its own ball, only where the video found it
    this.clip.update(this.clipSpeed);
    this.placeClipLabel();
    this.moveSpotlight();
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  };
}
