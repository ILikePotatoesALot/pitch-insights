import type { FocusMetric, Profile, ViewMode } from "./types";

// A viewer's profile is only their choices: club, player, mode, language, focus metric. No name, id or history is
// kept (Microsoft's Personalizer guidance: send aggregated features, never a user identifier). Reading and writing
// goes through `ProfileStore`, so the Azure deployment can swap the browser's localStorage for Cosmos DB (a
// `RemoteProfileStore` with the same three methods) without touching the app.

export const FOCUS_OPTIONS: { key: FocusMetric; label: string; short: string }[] = [
  { key: "win_probability", label: "Win probability", short: "Win chance" },
  { key: "xt_added", label: "Threat added (xT)", short: "xT" },
  { key: "xg", label: "Expected goals (xG)", short: "xG" },
  { key: "pass_accuracy_pct", label: "Pass accuracy", short: "Pass accuracy" },
  { key: "possession_pct", label: "Possession", short: "Possession" },
  { key: "shots", label: "Shots", short: "Shots" },
];
const FOCUS_KEYS = FOCUS_OPTIONS.map((f) => f.key) as string[];
export const focusLabel = (key: string | null) => FOCUS_OPTIONS.find((f) => f.key === key)?.short ?? "";

/** The languages the replay server can have translations for (it lists the ones it really has once connected). */
export const LANGUAGE_NAMES: Record<string, string> = { en: "English", es: "Español", fr: "Français", de: "Deutsch", nl: "Nederlands", "zh-Hans": "简体中文" };

export const DEFAULT_PROFILE: Profile = { version: 1, mode: "analyst", lang: "en", team: null, player: null, focus: null };

export interface ProfileStore {
  load(): Promise<Profile | null>;
  save(profile: Profile): Promise<void>;
  clear(): Promise<void>;
}

const KEY = "pitch-insights.profile.v1";
const short = (v: unknown, max = 40): string | null => (typeof v === "string" && v.length > 0 && v.length <= max ? v : null);

/** A profile from untrusted data (storage, a link): anything wrong or missing falls back to the default. */
export function sanitize(raw: unknown): Profile {
  const r = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const mode = r.mode === "casual" || r.mode === "analyst" ? (r.mode as ViewMode) : DEFAULT_PROFILE.mode;
  const focus = typeof r.focus === "string" && FOCUS_KEYS.includes(r.focus) ? (r.focus as FocusMetric) : null;
  return { version: 1, mode, lang: short(r.lang, 12) ?? "en", team: short(r.team), player: short(r.player), focus };
}

/** Browser storage: wrapped in try/catch because it can be blocked, full or empty (private windows, cleared data). */
export class LocalProfileStore implements ProfileStore {
  async load() {
    try {
      const text = localStorage.getItem(KEY);
      return text ? sanitize(JSON.parse(text)) : null;
    } catch {
      return null;
    }
  }
  async save(profile: Profile) {
    try { localStorage.setItem(KEY, JSON.stringify(profile)); } catch { /* the profile just won't survive a reload */ }
  }
  async clear() {
    try { localStorage.removeItem(KEY); } catch { /* nothing to clear */ }
  }
}

export const profileStore: ProfileStore = new LocalProfileStore();

const PARAMS = ["mode", "lang", "team", "player", "focus"] as const;

/** A profile given in the page's URL (`?team=POT&player=POT-11&mode=casual&lang=de&focus=xg`), or null if none is.
 *  Such a profile belongs to that tab only: it is never saved, so two tabs with two profiles don't overwrite each other. */
export function profileFromUrl(search: string): Profile | null {
  const q = new URLSearchParams(search);
  if (!PARAMS.some((k) => q.has(k))) return null;
  const raw: Record<string, string | null> = {};
  for (const k of PARAMS) {
    if (!q.has(k)) continue;
    const v = q.get(k)!.trim();
    raw[k] = v === "" ? null : k === "team" || k === "player" ? v.toUpperCase() : k === "lang" ? v : v.toLowerCase();
  }
  return sanitize(raw);
}

export function profileToParams(p: Profile): string {
  const q = new URLSearchParams();
  q.set("mode", p.mode);
  q.set("lang", p.lang);
  if (p.team) q.set("team", p.team);
  if (p.player) q.set("player", p.player);
  if (p.focus) q.set("focus", p.focus);
  return q.toString();
}

/** The connection's query string for a profile: what the server's Director reads (mode, club, player, focus). */
export function connectionParams(p: Profile): string {
  const q = new URLSearchParams({ lang: p.lang, mode: p.mode });
  if (p.team) q.set("team", p.team);
  if (p.player) q.set("player", p.player);
  if (p.focus) q.set("focus", p.focus);
  return q.toString();
}
