import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { Overlays } from "./components/Overlays";
import { FocusStrip, MomentFeed, MomentumChart, PinnedPlayer, Ratings, Scoreboard, StatsPanel } from "./components/Panels";
import { ProfilePicker } from "./components/ProfilePicker";
import { DEFAULT_PROFILE, LANGUAGE_NAMES, profileFromUrl, profileStore, profileToParams } from "./profile";
import { PitchScene, teamColours } from "./pitch/PitchScene";
import type { ClubInfo, LayoutMode, MatchEvent, MatchMeta, MatchSummary, Profile, ViewMode } from "./types";
import { useReplay } from "./useReplay";

const SPEEDS = [1, 5, 20, 60];
// What a link can set besides the profile: `match` (a sample's name), `layout` (broadcast | fan) and `speed`, so
// two views of one match can be opened side by side (see CompareView) and set up the same way every time.
const query = new URLSearchParams(location.search);
const urlLayout: LayoutMode = query.get("layout") === "broadcast" ? "broadcast" : "fan";
const urlSpeed = Number(query.get("speed"));
const embedded = query.has("embed");

export default function App() {
  const [matches, setMatches] = useState<MatchSummary[]>([]);
  const [name, setName] = useState<string | null>(null);
  const [layout, setLayout] = useState<LayoutMode>(urlLayout);
  const [inspected, setInspected] = useState<string | null>(null);
  const [seekTo, setSeekTo] = useState(0);
  // The viewer's profile: from the link if it carries one (that tab only, never saved), else the store, else the
  // first-visit picker. Null until known; the match isn't started before then, so the server sees the right profile.
  const [profile, setProfile] = useState<Profile | null>(null);
  const [fromLink, setFromLink] = useState(false);
  const [picker, setPicker] = useState<"first" | "edit" | null>(null);
  const [clubs, setClubs] = useState<ClubInfo[]>([]);
  const [ratingHistory, setRatingHistory] = useState<number[]>([]);
  const sceneRef = useRef<PitchScene | null>(null);
  const pitchEl = useRef<HTMLDivElement>(null);
  const spotLabel = useRef<HTMLDivElement>(null);
  const firstHalfEnd = useRef<number | null>(null);
  const p = profile ?? DEFAULT_PROFILE;

  useEffect(() => {
    fetch("/api/matches").then((r) => r.json()).then((list: MatchSummary[]) => {
      setMatches(list);
      const wanted = query.get("match");
      if (list.length) setName(list.find((m) => m.name === wanted)?.name ?? list[0].name);
    }).catch(() => setMatches([]));
    fetch("/api/clubs").then((r) => r.json()).then(setClubs).catch(() => setClubs([]));
    const link = profileFromUrl(location.search);
    if (link) {
      setProfile(link);
      setFromLink(true);
    } else {
      profileStore.load().then((saved) => {
        setProfile(saved ?? DEFAULT_PROFILE);
        if (!saved) setPicker("first");
      });
    }
  }, []);

  useEffect(() => {
    if (!pitchEl.current) return;
    const scene = new PitchScene(pitchEl.current);
    sceneRef.current = scene;
    return () => scene.dispose();
  }, []);

  const onEvent = useCallback((ev: MatchEvent, meta: MatchMeta) => {
    if (ev.type === "match_state" && ev.state === "half_time") firstHalfEnd.current = ev.t;
    const t = ev.period === 2 ? (firstHalfEnd.current ?? 2700) + ev.t : ev.t;
    sceneRef.current?.addEvent(ev, meta, t);
  }, []);
  const onReset = useCallback(() => {
    firstHalfEnd.current = null;
    sceneRef.current?.reset();
  }, []);

  const ready = profile !== null && picker !== "first";
  const { meta, aiInfo, languages, state, moments, cues, status, speed, setSpeed, pause, resume, seek, seekAt } =
    useReplay(ready ? name : null, p, SPEEDS.includes(urlSpeed) ? urlSpeed : 20, onEvent, onReset);

  // A change to language, club, player or focus metric reconnects (the server works from the profile it was
  // given) from the current moment, not the start of the minute, so nothing replays. It goes by match seconds,
  // because a minute can't say first-half stoppage time (45+2'). Before the first state arrives there is no
  // current moment, so the reconnect keeps the jump already made. Mode alone doesn't reconnect.
  const reconnectHere = () => {
    if (state?.period === 1) seekAt(state.match_minute * 60);
    else if (state) seekAt((firstHalfEnd.current ?? 2700) + (state.match_minute - 45) * 60);
  };
  const commit = (next: Profile, save = true) => {
    const key = (q: Profile) => [q.lang, q.team, q.player, q.focus].join("|");
    if (key(next) !== key(p)) reconnectHere();
    setProfile(next);
    if (!save) return;
    if (fromLink) {
      const q = new URLSearchParams(location.search);
      for (const [k, v] of new URLSearchParams(profileToParams(next))) q.set(k, v);
      for (const k of ["team", "player", "focus"] as const) if (!next[k]) q.delete(k);
      history.replaceState(null, "", `?${q}`);
    } else {
      void profileStore.save(next);
    }
  };
  const reset = () => {
    void profileStore.clear(); // nothing is kept: the next visit starts with the welcome picker again
    commit({ ...DEFAULT_PROFILE, lang: p.lang }, false);
    setPicker(null);
  };

  useEffect(() => {
    if (meta) sceneRef.current?.setMatch(meta);
    setInspected(null);
  }, [meta]);

  const colours = useMemo<[string, string]>(() => {
    if (!meta) return ["#4f7cff", "#ff5a5a"];
    const [h, a] = teamColours(meta);
    return [`#${h.getHexString()}`, `#${a.getHexString()}`];
  }, [meta]);

  // The favourite player: who they are in this match (none if they aren't playing), for the spotlight and the card.
  const pinned = useMemo(() => {
    if (!meta || !p.player) return null;
    const home = meta.home.players.find((x) => x.id === p.player);
    const person = home ?? meta.away.players.find((x) => x.id === p.player);
    return person ? { ...person, colour: home ? colours[0] : colours[1] } : null;
  }, [meta, p.player, colours]);

  useEffect(() => {
    sceneRef.current?.setSpotlight(pinned ? { id: pinned.id, colour: pinned.colour } : null, spotLabel.current);
  }, [pinned, meta]);

  // The favourite's rating, one sample a match minute, for the card's sparkline. It survives a reconnect at the
  // same moment (a language change) and starts again if the match goes back (a jump) or the player changes.
  const lastSample = useRef<number>(-1);
  useEffect(() => { lastSample.current = -1; setRatingHistory([]); }, [name, p.player]);
  useEffect(() => {
    const me = state?.players.find((x) => x.player_id === p.player);
    if (!state || !me) return;
    const minute = (state.period === 2 ? 45 : 0) + state.match_minute;
    if (minute === lastSample.current) return;
    const back = minute < lastSample.current;
    lastSample.current = minute;
    setRatingHistory((h) => [...(back ? [] : h), me.rating]);
  }, [state, p.player]);

  const clubName = meta && p.team ? [meta.home, meta.away].find((t) => t.id === p.team)?.short_name : undefined;
  const clubAbsent = !!(meta && p.team && !clubName);
  const accent = meta && p.team === meta.home.id ? colours[0] : meta && p.team === meta.away.id ? colours[1] : undefined;
  const chip = [p.team ? `★ ${clubs.find((c) => c.id === p.team)?.short_name ?? p.team}` : "Profile", p.mode === "casual" ? "Casual" : "Analyst",
                LANGUAGE_NAMES[p.lang] ?? p.lang].join(" · ");
  const compareHref = `?compare=1&match=${name ?? ""}&speed=${speed}`;

  return (
    <div className={`app ${layout}${embedded ? " embed" : ""}`} style={accent ? ({ "--fav": accent } as CSSProperties) : undefined}>
      <header>
        <h1>Pitch Insights <small>live football intelligence</small></h1>
        <select value={name ?? ""} onChange={(e) => setName(e.target.value)} aria-label="Match">
          {matches.map((m) => <option key={m.name} value={m.name}>{m.home.name} v {m.away.name} ({m.name.split("-")[0]})</option>)}
        </select>
        <select value={p.lang} onChange={(e) => commit({ ...p, lang: e.target.value })} aria-label="Language">
          {Object.entries(languages).map(([code, label]) => <option key={code} value={code}>{label}</option>)}
        </select>
        <div className="segmented" role="group" aria-label="Layout">
          {(["broadcast", "fan"] as LayoutMode[]).map((v) => (
            <button key={v} className={layout === v ? "on" : ""} onClick={() => setLayout(v)}
                    title={v === "broadcast" ? "The pitch and its overlays only" : "Adds the side panel"}>{v === "broadcast" ? "Broadcast" : "Fan"}</button>
          ))}
        </div>
        <div className="segmented" role="group" aria-label="Viewer mode">
          {(["casual", "analyst"] as ViewMode[]).map((v) => (
            <button key={v} className={p.mode === v ? "on" : ""} onClick={() => commit({ ...p, mode: v })}>{v === "casual" ? "Casual fan" : "Analyst"}</button>
          ))}
        </div>
        <button className={`profile-chip${accent ? " fav" : ""}`} onClick={() => setPicker("edit")} aria-label="Edit your profile"
                title={clubAbsent ? "Your club isn't playing in this match" : "Edit your profile"}>
          {chip}{clubAbsent && " (not in this match)"}
        </button>
        {!embedded && <a className="compare" href={compareHref} target="_blank" rel="noreferrer" title="Open two viewers of this match side by side">Compare viewers</a>}
      </header>

      <main>
        <section className="stage">
          {meta && <Scoreboard meta={meta} state={state} colours={colours} />}
          {meta && <FocusStrip meta={meta} state={state} colours={colours} focus={p.focus} />}
          {meta && pinned && <PinnedPlayer state={state} meta={meta} colours={colours} playerId={pinned.id} mode={p.mode} focus={p.focus}
                                           history={ratingHistory} onChange={() => setPicker("edit")} />}
          <div className="pitch" ref={pitchEl}>
            {pinned && <div className="spot-label" ref={spotLabel} style={{ borderColor: pinned.colour }}>#{pinned.number} {pinned.name.split(" ").slice(-1)[0]}</div>}
            {meta && <Overlays cues={cues} meta={meta} mode={p.mode} colours={colours} />}
            {status === "connecting" && <div className="overlay-msg">Connecting to the replay server…</div>}
            {status === "error" && <div className="overlay-msg">Can't reach the replay server. Is it running on port 8000?</div>}
            {status === "disconnected" && <div className="overlay-msg">Lost the connection to the replay server. Pick a minute and press Go to reconnect.</div>}
          </div>
          <div className="controls">
            {status === "paused" ? <button onClick={resume}>Play</button> : <button onClick={pause} disabled={status !== "live"}>Pause</button>}
            <div className="segmented" role="group" aria-label="Speed">
              {SPEEDS.map((s) => <button key={s} className={speed === s ? "on" : ""} onClick={() => setSpeed(s)}>{s}×</button>)}
            </div>
            <label className="seek">
              Jump to <input type="range" min={0} max={90} step={1} value={seekTo} onChange={(e) => setSeekTo(Number(e.target.value))} />
              <b>{seekTo}'</b>
              <button onClick={() => seek(seekTo)}>Go</button>
            </label>
            {status === "ended" && <span className="status">Match over</span>}
          </div>
          <MomentumChart state={state} colours={colours} />
          <p className="legend">
            The surface rises where each team has been active in the last two minutes, coloured by which team owns that space.
            Spikes are shots: the taller, the better the chance. Goals glow.
            {pinned && " The ring follows your player: it sits where they last touched the ball."}
          </p>
        </section>

        {layout === "fan" && <aside>
          {meta && <MomentFeed moments={moments} meta={meta} aiInfo={aiInfo} mode={p.mode} colours={colours} />}
          {meta && <Ratings state={state} meta={meta} colours={colours} favourite={inspected} setFavourite={setInspected} />}
          {meta && p.mode === "analyst" && <StatsPanel state={state} meta={meta} focus={p.focus} />}
        </aside>}
      </main>

      {picker && <ProfilePicker clubs={clubs} languages={languages} profile={p} first={picker === "first"} fromLink={fromLink}
                                onSave={(next) => { commit(next); setPicker(null); }} onReset={reset} onClose={() => setPicker(null)} />}
    </div>
  );
}
