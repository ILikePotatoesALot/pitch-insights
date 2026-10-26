import * as THREE from "three";
import type { DrawnPlayer } from "./ClipLayer";
import { TrackingHistory } from "./TrackingHistory";

export interface PlayerContextOptions { trail: boolean; nearby: boolean }
const CAPACITY = 256 * 6; // ribbon vertices, subdivided at one metre to follow the terrain
const RADIUS = 12;
const WHITE = new THREE.Color("#ffffff");

/** The selected player's observed path and the players within twelve metres. */
export class PlayerContextLayer {
  readonly group = new THREE.Group();
  readonly history = new TrackingHistory();
  private ribbon: THREE.Mesh;
  private boundary: THREE.LineLoop;
  private rings = new Map<string, THREE.Mesh>();
  private ringGeometry = new THREE.RingGeometry(1.6, 2.1, 24);
  private tint = new THREE.Color();

  constructor(private heightAt: (x: number, z: number) => number) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(CAPACITY * 3), 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(new Float32Array(CAPACITY * 3), 3));
    geometry.setDrawRange(0, 0);
    this.ribbon = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ vertexColors: true,
      transparent: true, opacity: 0.9, depthWrite: false, depthTest: false, side: THREE.DoubleSide }));
    this.ribbon.frustumCulled = false;
    this.ribbon.renderOrder = 3;
    const boundaryGeometry = new THREE.BufferGeometry();
    boundaryGeometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(64 * 3), 3));
    this.boundary = new THREE.LineLoop(boundaryGeometry, new THREE.LineBasicMaterial({ transparent: true,
      opacity: 0.35, depthWrite: false, depthTest: false }));
    this.boundary.frustumCulled = false;
    this.boundary.renderOrder = 2;
    this.group.add(this.ribbon, this.boundary);
    this.group.visible = false;
  }

  clear() {
    this.history.reset();
    this.group.visible = false;
    this.ribbon.geometry.setDrawRange(0, 0);
    for (const ring of this.rings.values()) ring.visible = false;
  }

  update(t: number, selected: string | null, players: ReadonlyMap<string, DrawnPlayer>, colours: THREE.Color[], options: PlayerContextOptions) {
    const player = selected ? players.get(selected) : undefined;
    this.group.visible = !!player && (options.trail || options.nearby);
    this.ribbon.visible = !!player && options.trail;
    this.boundary.visible = !!player && options.nearby;
    for (const ring of this.rings.values()) ring.visible = false;
    if (!player || !selected || !this.group.visible) return;
    const colour = colours[player.team] ?? WHITE;
    if (options.trail) {
      const positions = this.ribbon.geometry.getAttribute("position") as THREE.BufferAttribute;
      const shades = this.ribbon.geometry.getAttribute("color") as THREE.BufferAttribute;
      let vertex = 0;
      const segments = this.history.segments(selected, t, { x: player.x + 52.5, y: 34 - player.z });
      for (const segment of segments) {
        const dx = segment.b.x - segment.a.x, dz = segment.a.y - segment.b.y;
        const length = Math.hypot(dx, dz);
        if (length < 0.03) continue;
        const steps = Math.ceil(length);
        const nx = -dz / length * 0.3, nz = dx / length * 0.3;
        this.tint.copy(colour).lerp(WHITE, 0.45).multiplyScalar(Math.max(0.15, 1 - (t - segment.t) / 8));
        for (let step = 0; step < steps && vertex + 6 <= CAPACITY; step++) {
          const a = step / steps, b = (step + 1) / steps;
          const ax = segment.a.x - 52.5 + dx * a, az = 34 - segment.a.y + dz * a;
          const bx = segment.a.x - 52.5 + dx * b, bz = 34 - segment.a.y + dz * b;
          for (const [x, z] of [[ax + nx, az + nz], [ax - nx, az - nz], [bx + nx, bz + nz],
                                [bx + nx, bz + nz], [ax - nx, az - nz], [bx - nx, bz - nz]]) {
            positions.setXYZ(vertex, x, this.heightAt(x, z) + 0.35, z);
            shades.setXYZ(vertex++, this.tint.r, this.tint.g, this.tint.b);
          }
        }
      }
      this.ribbon.geometry.setDrawRange(0, vertex);
      positions.needsUpdate = shades.needsUpdate = true;
    }
    if (!options.nearby) return;
    (this.boundary.material as THREE.LineBasicMaterial).color.copy(colour);
    const outline = this.boundary.geometry.getAttribute("position") as THREE.BufferAttribute;
    for (let i = 0; i < 64; i++) {
      const angle = i * Math.PI * 2 / 64;
      const x = Math.max(-52.5, Math.min(52.5, player.x + RADIUS * Math.cos(angle)));
      const z = Math.max(-34, Math.min(34, player.z + RADIUS * Math.sin(angle)));
      outline.setXYZ(i, x, this.heightAt(x, z) + 0.3, z);
    }
    outline.needsUpdate = true;
    for (const [id, other] of players) {
      if (id === selected || other.team === 2 || Math.hypot(other.x - player.x, other.z - player.z) > RADIUS) continue;
      let ring = this.rings.get(id);
      if (!ring) {
        ring = new THREE.Mesh(this.ringGeometry, new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.8,
          depthWrite: false, depthTest: false, side: THREE.DoubleSide }));
        ring.rotation.x = -Math.PI / 2;
        ring.renderOrder = 4;
        this.group.add(ring);
        this.rings.set(id, ring);
      }
      (ring.material as THREE.MeshBasicMaterial).color.copy(colours[other.team]);
      ring.position.set(other.x, this.heightAt(other.x, other.z) + 0.4, other.z);
      ring.visible = true;
    }
  }

  dispose() {
    this.ribbon.geometry.dispose();
    (this.ribbon.material as THREE.Material).dispose();
    this.boundary.geometry.dispose();
    (this.boundary.material as THREE.Material).dispose();
    this.ringGeometry.dispose();
    for (const ring of this.rings.values()) (ring.material as THREE.Material).dispose();
  }
}
