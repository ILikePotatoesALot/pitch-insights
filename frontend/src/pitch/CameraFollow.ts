export type CameraMode = "full" | "ball" | "player" | "manual";
interface Point { x: number; z: number }

/** Keep a useful amount of surrounding pitch visible, even near a touchline. */
export function cameraFocus(mode: CameraMode, ball: Point | null, player: Point | undefined): Point | null {
  const point = mode === "ball" ? ball : mode === "player" ? player : null;
  return point ? { x: Math.max(-35, Math.min(35, point.x)), z: Math.max(-20, Math.min(20, point.z)) } : null;
}

export function cameraBlend(seconds: number): number {
  return 1 - Math.exp(-Math.min(0.1, Math.max(0, seconds)) / 0.6);
}
