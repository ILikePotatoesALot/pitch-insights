import * as THREE from "three";
import type { MatchMeta } from "../types";
import type { DrawnPlayer } from "./ClipLayer";
import { FormationTracker } from "./FormationTracker";

export type FormationTeam = "home" | "away";
export type FormationLabels = [string | null, string | null];
const CAPACITY = 1200 * 6; // terrain-following ribbon vertices per team

/** Connect each observed depth band across the pitch, at the markers' drawing time. */
export class FormationLayer {
  readonly group = new THREE.Group();
  private trackers = [new FormationTracker(), new FormationTracker()];
  private ribbons: THREE.Mesh[];
  private meta: MatchMeta | null = null;
  private keepers = new Set<string>();
  private enabled = false;
  private team: FormationTeam = "home";
  private labels: FormationLabels = [null, null];
  private onChange: ((labels: FormationLabels) => void) | null = null;

  constructor(private heightAt: (x: number, z: number) => number) {
    this.ribbons = [0, 1].map(() => {
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(CAPACITY * 3), 3));
      geometry.setDrawRange(0, 0);
      const ribbon = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.8,
        depthWrite: false, depthTest: false, side: THREE.DoubleSide }));
      ribbon.frustumCulled = false;
      ribbon.renderOrder = 2;
      this.group.add(ribbon);
      return ribbon;
    });
    this.group.visible = false;
  }

  setMatch(meta: MatchMeta) {
    this.meta = meta;
    this.keepers = new Set([...meta.home.players, ...meta.away.players].filter((p) => p.position === "GK").map((p) => p.id));
    this.clear();
  }

  setOptions(enabled: boolean, team: FormationTeam) {
    if (this.enabled !== enabled || this.team !== team) this.clear();
    this.enabled = enabled;
    this.team = team;
    if (!enabled) this.group.visible = false;
  }

  setOnChange(callback: ((labels: FormationLabels) => void) | null) { this.onChange = callback; }

  private announce(labels: FormationLabels) {
    if (labels.some((label, side) => label !== this.labels[side])) {
      this.labels = labels;
      this.onChange?.(labels);
    }
  }

  clear() {
    this.trackers.forEach((tracker) => tracker.reset());
    this.ribbons.forEach((ribbon) => ribbon.geometry.setDrawRange(0, 0));
    this.group.visible = false;
    this.announce([null, null]);
  }

  update(t: number, players: ReadonlyMap<string, DrawnPlayer>, colours: THREE.Color[], period: number, phase: string) {
    if (!this.enabled || !this.meta?.tracking || (phase !== "open_play" && phase !== "keeper_ball")) {
      if (this.group.visible) this.clear();
      return;
    }
    this.group.visible = true;
    const labels: FormationLabels = [null, null];
    const dirs = this.meta.attacking_direction[String(period)];
    for (const side of [0, 1] as const) {
      const ribbon = this.ribbons[side];
      ribbon.geometry.setDrawRange(0, 0);
      if ((side === 0 && this.team === "away") || (side === 1 && this.team === "home")) continue;
      const teamId = side === 0 ? this.meta.home.id : this.meta.away.id;
      const direction = dirs?.[teamId];
      if (!direction) { this.trackers[side].reset(); continue; }
      const points = [...players].filter(([id, p]) => p.team === side && !this.keepers.has(id));
      const shape = this.trackers[side].update(t, points.map(([id, p]) => ({ id,
        depth: direction === "right_to_left" ? -p.x : p.x })));
      if (!shape) continue;
      labels[side] = shape.label;
      (ribbon.material as THREE.MeshBasicMaterial).color.copy(colours[side]);
      const positions = ribbon.geometry.getAttribute("position") as THREE.BufferAttribute;
      let vertex = 0;
      for (const line of shape.lines) {
        const band = line.map((id) => players.get(id)!).sort((a, b) => a.z - b.z);
        for (let i = 1; i < band.length; i++) {
          const a = band[i - 1], b = band[i];
          const dx = b.x - a.x, dz = b.z - a.z;
          const length = Math.hypot(dx, dz);
          if (length < 0.05) continue;
          const steps = Math.ceil(length);
          const nx = -dz / length * 0.18, nz = dx / length * 0.18;
          for (let step = 0; step < steps && vertex + 6 <= CAPACITY; step++) {
            const ax = a.x + dx * step / steps, az = a.z + dz * step / steps;
            const bx = a.x + dx * (step + 1) / steps, bz = a.z + dz * (step + 1) / steps;
            for (const [x, z] of [[ax + nx, az + nz], [ax - nx, az - nz], [bx + nx, bz + nz],
                                  [bx + nx, bz + nz], [ax - nx, az - nz], [bx - nx, bz - nz]])
              positions.setXYZ(vertex++, x, this.heightAt(x, z) + 0.45, z);
          }
        }
      }
      positions.needsUpdate = true;
      ribbon.geometry.setDrawRange(0, vertex);
    }
    this.announce(labels);
  }

  dispose() {
    for (const ribbon of this.ribbons) {
      ribbon.geometry.dispose();
      (ribbon.material as THREE.Material).dispose();
    }
  }
}
