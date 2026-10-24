import { useEffect, useRef, useState } from "react";
import { remoteServer } from "../api";
import { DEFAULT_PROFILE, FOCUS_OPTIONS, LANGUAGE_NAMES } from "../profile";
import type { ClubInfo, FocusMetric, Profile, ViewMode } from "../types";

/**
 * The profile picker: a first-visit welcome (club, player, mode, language, focus metric) and the same form for
 * editing later from the header. Nothing here is required; the viewer can skip it or clear it, and what is
 * stored is only these five choices.
 */
export function ProfilePicker({ clubs, languages, profile, first, fromLink, onSave, onReset, onClose }: {
  clubs: ClubInfo[]; languages: Record<string, string>; profile: Profile; first: boolean; fromLink: boolean;
  onSave: (p: Profile) => void; onReset: () => void; onClose: () => void;
}) {
  const [draft, setDraft] = useState<Profile>(profile);
  const firstField = useRef<HTMLButtonElement>(null);
  const set = (patch: Partial<Profile>) => setDraft((d) => ({ ...d, ...patch }));
  const langs = { ...LANGUAGE_NAMES, ...languages };

  // The parent re-renders on every replay update and passes a new `onClose` each time: keep it in a ref, so
  // neither effect re-runs and the focus stays on the field the viewer is using.
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => { firstField.current?.focus(); }, []);
  useEffect(() => {
    if (first) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && closeRef.current();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [first]);

  const pickClub = (team: string | null) => {
    // Choosing a club drops a player that came from the club chosen before (so the list isn't left on a stale pick);
    // a player from any other club was picked on purpose and stays.
    const fromOldClub = clubs.find((c) => c.id === draft.team)?.players.some((p) => p.id === draft.player);
    set({ team, player: team && fromOldClub ? null : draft.player });
  };
  const ordered = [...clubs].sort((a, b) => (a.id === draft.team ? -1 : b.id === draft.team ? 1 : 0));

  return (
    <div className="modal-backdrop" role="presentation">
      <form className="picker" role="dialog" aria-modal="true" aria-labelledby="picker-title"
            onSubmit={(e) => { e.preventDefault(); onSave(draft); }}>
        <h2 id="picker-title">{first ? "Make it yours" : "Your profile"}</h2>
        <p className="picker-note">
          {first ? "Pick a club and a player and the app follows them: a spotlight on the pitch, a pinned card, alerts. " : ""}
          {fromLink ? "This view was opened from a link, so its profile lives in the link and isn't saved. " : (remoteServer ? "Saved in this browser and, under a random id, in this app's Azure Cosmos DB (deleted after 90 days unused), and only these choices: no name, no account. " : "Saved only in this browser, and only these choices: no name, no account. ")}
          Everything is optional.
        </p>

        <fieldset>
          <legend>Favourite club</legend>
          <div className="chips">
            <button type="button" ref={firstField} className={draft.team === null ? "on" : ""} onClick={() => pickClub(null)}>None</button>
            {clubs.map((c) => (
              <button type="button" key={c.id} className={draft.team === c.id ? "on" : ""} onClick={() => pickClub(c.id)}>
                <i style={{ background: c.colours.primary }} />{c.name}
              </button>
            ))}
          </div>
        </fieldset>

        <label className="field">Favourite player
          <select value={draft.player ?? ""} onChange={(e) => set({ player: e.target.value || null })}>
            <option value="">None</option>
            {ordered.map((c) => (
              <optgroup key={c.id} label={c.name}>
                {c.players.map((p) => <option key={p.id} value={p.id}>#{p.number} {p.name} · {p.position}</option>)}
              </optgroup>
            ))}
          </select>
        </label>

        <fieldset>
          <legend>How much detail</legend>
          <div className="segmented" role="group" aria-label="Mode">
            {(["casual", "analyst"] as ViewMode[]).map((m) => (
              <button type="button" key={m} className={draft.mode === m ? "on" : ""} onClick={() => set({ mode: m })}>
                {m === "casual" ? "Casual fan" : "Analyst"}
              </button>
            ))}
          </div>
          <small>{draft.mode === "casual" ? "The big moments, plain words." : "Evidence, stats and rating changes too."}</small>
        </fieldset>

        <label className="field">Language
          <select value={draft.lang} onChange={(e) => set({ lang: e.target.value })}>
            {Object.entries(langs).map(([code, label]) => <option key={code} value={code}>{label}</option>)}
          </select>
        </label>

        <label className="field">Focus metric
          <select value={draft.focus ?? ""} onChange={(e) => set({ focus: (e.target.value || null) as FocusMetric | null })}>
            <option value="">None</option>
            {FOCUS_OPTIONS.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
          </select>
          <small>Shown under the scoreboard, first on every stat card and highlighted in the side panel.</small>
        </label>

        <div className="picker-actions">
          <button type="submit" className="primary">{first ? "Start watching" : "Save"}</button>
          {first
            ? <button type="button" onClick={() => onSave({ ...DEFAULT_PROFILE, lang: draft.lang })}>Skip</button>
            : <button type="button" onClick={onClose}>Cancel</button>}
          {!first && !fromLink && <button type="button" className="link" onClick={onReset}>Clear my profile</button>}
        </div>
      </form>
    </div>
  );
}
