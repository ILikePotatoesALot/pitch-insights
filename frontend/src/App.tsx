import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { ClipBanner, ClipCredit, ClipEvents, ClipPanel, ClipPinned, ClipPlayers, mmss } from "./components/ClipPanels";
import { TrackingTotals, type ClipTracking } from "./clipStats";
import { Overlays } from "./components/Overlays";
import { FocusStrip, MomentFeed, MomentumChart, PinnedPlayer, Ratings, Scoreboard, StatsPanel } from "./components/Panels";
import { ProfilePicker } from "./components/ProfilePicker";
import { ThemeSwitch } from "./components/ThemeSwitch";
import { ReplaySeek } from "./components/ReplaySeek";
import { PositionInsights } from "./components/PositionInsights";
import { apiUrl } from "./api";
import { DEFAULT_PROFILE, LANGUAGE_NAMES, profileFromUrl, profileStore, profileToParams } from "./profile";
import { trackLabel } from "./pitch/ClipLayer";
import { PitchScene, teamColours, type SurfaceView } from "./pitch/PitchScene";
import type { CameraMode } from "./pitch/CameraFollow";
import type { ClipEvent, ClipFrame, ClubInfo, LayoutMode, MatchEvent, MatchMeta, MatchSummary, Profile, ViewMode } from "./types";
import { useReplay } from "./useReplay";

const SPEEDS = [1, 5, 20, 60];
const CLIP_SPEEDS = [0.5, 1, 2, 5]; // the clip is 100 s of real footage: slower than a synthetic match, and it starts at 1x
// What a link can set besides the profile: `match` (a sample's name), `layout` (broadcast | fan) and `speed`, so
// two views of one match can be opened side by side (see CompareView) and set up the same way every time.
const query = new URLSearchParams(location.search);
const urlLayout: LayoutMode = query.get("layout") === "broadcast" ? "broadcast" : "fan";
const urlSpeed = Number(query.get("speed"));
const embedded = query.has("embed");
const syncEpoch = query.has("sync") ? Number(query.get("sync")) : null;
const controlled = embedded && syncEpoch !== null && Number.isSafeInteger(syncEpoch);
// A tracked player to follow in a clip ("L-t11"): not part of the profile, since tracker numbers belong to one clip.
const urlFollow = /^[LR]-t\d+$/.test(query.get("follow") ?? "") ? query.get("follow") : null;
const NO_TRACKING: ClipTracking = { players: [], possession: [0, 0] };
type DetailPanel = "moments" | "players" | "stats";

export default function App() {
  const [matches, setMatches] = useState<MatchSummary[]>([]);
  const [name, setName] = useState<string | null>(null);
  const [layout, setLayout] = useState<LayoutMode>(urlLayout);
  const [inspected, setInspected] = useState<string | null>(null);
  const [seekTo, setSeekTo] = useState(0);
  const [surfaceView, setSurfaceView] = useState<SurfaceView>("current");
  const [showTrail, setShowTrail] = useState(true);
  const [showNearby, setShowNearby] = useState(true);
  const [cameraMode, setCameraMode] = useState<CameraMode>("full");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [panel, setPanel] = useState<DetailPanel>("moments");
  const settingsButton = useRef<HTMLButtonElement>(null);
  const appTitle = useRef<HTMLHeadingElement>(null);
  // Links supply a profile for this tab; otherwise restore the viewer's saved choices or start watching immediately.
  const [profile, setProfile] = useState<Profile | null>(null);
  const [fromLink, setFromLink] = useState(false);
  const [picker, setPicker] = useState<"edit" | null>(null);
  const [welcome, setWelcome] = useState(false);
  const [clubs, setClubs] = useState<ClubInfo[]>([]);
  const [ratingHistory, setRatingHistory] = useState<number[]>([]);
  const sceneRef = useRef<PitchScene | null>(null);
  const pitchEl = useRef<HTMLDivElement>(null);
  const spotLabel = useRef<HTMLDivElement>(null);
  const [follow, setFollow] = useState<string | null>(urlFollow);
  const tracking = useRef(new TrackingTotals());
  const [trackingView, setTrackingView] = useState<ClipTracking>(NO_TRACKING);
  const trackingShown = useRef(0);
  const firstHalfEnd = useRef<number | null>(null);
  const p = profile ?? DEFAULT_PROFILE;

  useEffect(() => {
    fetch(apiUrl("/api/matches")).then((r) => r.json()).then((list: MatchSummary[]) => {
      setMatches(list);
      const wanted = query.get("match");
      if (list.length) setName(list.find((m) => m.name === wanted)?.name ?? list[0].name);
    }).catch(() => setMatches([]));
    fetch(apiUrl("/api/clubs")).then((r) => r.json()).then(setClubs).catch(() => setClubs([]));
    const link = profileFromUrl(location.search);
    if (link) {
      setProfile(link);
      setFromLink(true);
    } else {
      profileStore.load().then((saved) => {
        setProfile(saved ?? DEFAULT_PROFILE);
        setWelcome(!saved);
      });
    }
  }, []);

  useEffect(() => {
    if (!pitchEl.current) return;
    const scene = new PitchScene(pitchEl.current);
    sceneRef.current = scene;
    scene.setOnPick((id) => setFollow(id));
    scene.setOnCameraMode(setCameraMode);
    return () => scene.dispose();
  }, []);

  const onEvent = useCallback((ev: MatchEvent, meta: MatchMeta) => {
    if (meta.source === "video") return sceneRef.current?.addClipEvent(ev as ClipEvent, meta);
    if (meta.tracking) {
      if (ev.x !== undefined && ev.y !== undefined) sceneRef.current?.addClipEvent(ev as ClipEvent, meta);
      return;
    }
    if (ev.type === "match_state" && ev.state === "half_time") firstHalfEnd.current = ev.t;
    const t = ev.period === 2 ? (firstHalfEnd.current ?? 2700) + ev.t : ev.t;
    sceneRef.current?.addEvent(ev, meta, t);
  }, []);
  const onReset = useCallback(() => {
    firstHalfEnd.current = null;
    sceneRef.current?.reset();
    tracking.current.reset();
    trackingShown.current = Number.NEGATIVE_INFINITY;
    setTrackingView(NO_TRACKING);
  }, []);

  const onFrame = useCallback((frame: ClipFrame, meta: MatchMeta) => {
    sceneRef.current?.showFrame(frame, meta);
    if (meta.tracking) return;
    tracking.current.push(frame, meta);
    const now = performance.now();
    if (now - trackingShown.current > 500) { // the panels redraw twice a second, not on every frame
      trackingShown.current = now;
      setTrackingView(tracking.current.snapshot());
    }
  }, []);

  const onPositions = useCallback((events: MatchEvent[], meta: MatchMeta) => {
    sceneRef.current?.restorePlayerPositions(events, meta);
  }, []);

  // A clip of real footage (the video path) has its own speeds, panels and controls; a synthetic match is as before.
  const clipMode = matches.find((m) => m.name === name)?.kind === "video";
  const simulationMode = !!matches.find((m) => m.name === name)?.tracking;
  const speeds = clipMode || simulationMode ? CLIP_SPEEDS : SPEEDS;
  const ready = profile !== null;
  const { meta, aiInfo, languages, state, moments, cues, status, speed, setSpeed, pause, resume, command, seek, seekAt, restart, clip, clipEvents, clipT, position } =
    useReplay(ready ? name : null, p, speeds.includes(urlSpeed) ? urlSpeed : clipMode || simulationMode ? 1 : 20, onEvent, onReset, onFrame, onPositions, {
      controlled,
      initialMinute: controlled ? Math.max(0, Number(query.get("from")) || 0) : 0,
      initialAt: controlled && query.has("at") ? Math.max(0, Number(query.get("at")) || 0) : null,
      onReady: (data) => { if (controlled) window.parent.postMessage({ type: "ready", epoch: syncEpoch, ready: data }, location.origin); },
    });
  const commandRef = useRef(command);
  commandRef.current = command;
  useEffect(() => {
    if (!controlled) return;
    const receive = (event: MessageEvent) => {
      if (event.origin !== location.origin || event.source !== window.parent || event.data?.type !== "seize:command" || event.data.epoch !== syncEpoch) return;
      const action = event.data.action;
      if (action && ["pause", "resume", "speed"].includes(action.cmd)) commandRef.current(action);
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, []);
  useEffect(() => {
    if (controlled && status === "ended") window.parent.postMessage({ type: "ended", epoch: syncEpoch }, location.origin);
    if (controlled && (status === "error" || status === "disconnected")) window.parent.postMessage({ type: "fault", epoch: syncEpoch }, location.origin);
  }, [status]);
  const showingClip = clipMode && meta?.source === "video"; // (the old match's meta stays for a moment after a switch)
  const showingMatch = !clipMode && !!meta && meta.source !== "video";
  useEffect(() => { sceneRef.current?.setClipSpeed(speed); }, [speed]);
  useEffect(() => { sceneRef.current?.setSurfaceView(clipMode || simulationMode ? surfaceView : "history"); }, [surfaceView, clipMode, simulationMode]);
  useEffect(() => { sceneRef.current?.setPlayerContext({ trail: showTrail, nearby: showNearby }); }, [showTrail, showNearby]);
  useEffect(() => {
    // Manual controls also work on event-only matches. Only automatic following needs tracking.
    sceneRef.current?.setCameraMode(clipMode || simulationMode || cameraMode === "manual" ? cameraMode : "full");
  }, [cameraMode, clipMode, simulationMode]);

  // A change to language, club, player or focus metric reconnects (the server works from the profile it was
  // given) from the current moment, not the start of the minute, so nothing replays. It goes by match seconds,
  // because a minute can't say first-half stoppage time (45+2'). Before the first state arrives there is no
  // current moment, so the reconnect keeps the jump already made. Mode alone doesn't reconnect.
  const reconnectHere = () => {
    if (showingClip) seekAt(Math.max(0, (clipT ?? 0) - (clip?.clip.start ?? 0)));
    else if (simulationMode) seekAt(clipT ?? 0);
    else if (state?.period === 1) seekAt(state.match_minute * 60);
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
    void profileStore.clear();
    commit({ ...DEFAULT_PROFILE, lang: p.lang }, false);
    setPicker(null);
    setWelcome(true);
  };
  const watchDemo = () => {
    const demo = matches.find((m) => m.name === "comeback-POT-CAR") ?? matches.find((m) => m.kind !== "video");
    if (!demo) return;
    const club = clubs.find((c) => c.id === demo.home.id);
    const squad = club?.players ?? (meta?.home.id === demo.home.id ? meta.home.players : meta?.away.id === demo.home.id ? meta.away.players : []);
    const player = squad.find((person) => person.number === 11) ?? squad[0];
    setName(demo.name);
    setSeekTo(0);
    setFollow(null);
    clearHistory();
    // A demo preset is for this visit. Only an explicit profile edit saves choices.
    commit({ ...DEFAULT_PROFILE, team: demo.home.id, player: player?.id ?? null, focus: "win_probability" }, false);
    restart();
    setWelcome(false);
  };

  useEffect(() => {
    if (meta) sceneRef.current?.setMatch(meta);
  }, [meta]);
  useEffect(() => { setInspected(null); }, [name]);

  const colours = useMemo<[string, string]>(() => {
    if (!meta) return ["#4f7cff", "#ff5a5a"];
    const [h, a] = teamColours(meta);
    return [`#${h.getHexString()}`, `#${a.getHexString()}`];
  }, [meta]);

  // The favourite player: who they are in this match (none if they aren't playing), for the spotlight and the card.
  const pinned = useMemo(() => {
    const id = simulationMode && follow ? follow : p.player;
    if (!meta || !id) return null;
    const home = meta.home.players.find((x) => x.id === id);
    const person = home ?? meta.away.players.find((x) => x.id === id);
    return person ? { ...person, colour: home ? colours[0] : colours[1] } : null;
  }, [meta, p.player, colours, simulationMode, follow]);

  // In a clip the spotlight follows the tracked player the viewer picked; in a match, their favourite player.
  const followed = showingClip && follow ? { id: follow, colour: colours[follow.startsWith("L-") ? 0 : 1] } : null;
  const spotlit = showingClip ? followed : pinned;
  useEffect(() => {
    sceneRef.current?.setSpotlight(spotlit ? { id: spotlit.id, colour: spotlit.colour } : null, spotLabel.current);
  }, [spotlit?.id, spotlit?.colour, meta]); // (by id: `followed` is a new object every render)

  // The favourite's rating, one sample a match minute, for the card's sparkline. It survives a reconnect at the
  // same moment (a language change) and starts again when the viewer jumps to another minute or changes player.
  // A sample is keyed by period and minute, not compared as a number: the second half starts again near 45.
  const lastSample = useRef("");
  const clearHistory = useCallback(() => { lastSample.current = ""; setRatingHistory([]); }, []);
  useEffect(clearHistory, [name, pinned?.id, clearHistory]);
  useEffect(() => {
    const me = state?.players.find((x) => x.player_id === pinned?.id);
    if (!state || !me) return;
    const key = `${state.period}:${state.match_minute}`;
    if (key === lastSample.current) return;
    lastSample.current = key;
    setRatingHistory((h) => [...h, me.rating]);
  }, [state, pinned?.id]);
  // Reconcile the spotlight with who is on the pitch (a sending-off or substitution may come from a state, not an event).
  useEffect(() => {
    const me = state?.players.find((x) => x.player_id === spotlit?.id);
    if (me) sceneRef.current?.setSpotlightOn(me.on_pitch);
  }, [state, spotlit?.id]);

  const clubName = meta && p.team ? [meta.home, meta.away].find((t) => t.id === p.team)?.short_name : undefined;
  const clubAbsent = !!(meta && p.team && !clubName);
  const accent = meta && p.team === meta.home.id ? colours[0] : meta && p.team === meta.away.id ? colours[1] : undefined;
  const actualLanguage = languages[p.lang] ? p.lang : "en";
  const chip = [p.team ? `★ ${clubs.find((c) => c.id === p.team)?.short_name ?? p.team}` : "Profile", p.mode === "casual" ? "Casual" : "Analyst",
                LANGUAGE_NAMES[actualLanguage] ?? actualLanguage].join(" · ");
  const compareHref = `?compare=1&match=${name ?? ""}&speed=${speed}`;
  const activePanel = panel === "stats" && !showingClip && p.mode !== "analyst" ? "moments" : panel;
  const panels: DetailPanel[] = showingClip || p.mode === "analyst" ? ["moments", "players", "stats"] : ["moments", "players"];

  return (
    <div className={`app ${layout}${embedded ? " embed" : ""}${controlled ? " sync" : ""}${accent ? " has-fav" : ""}`} style={accent ? ({ "--fav": accent } as CSSProperties) : undefined}>
      <header>
        <h1 ref={appTitle} tabIndex={-1}>Seize the game <small>live football intelligence</small></h1>
        <button type="button" className="mobile-settings-toggle" ref={settingsButton} aria-expanded={settingsOpen}
                aria-controls="view-settings" onClick={() => setSettingsOpen((open) => !open)}>Settings</button>
        <div className="header-settings" id="view-settings" data-open={settingsOpen} onKeyDown={(e) => {
          if (e.key === "Escape") { setSettingsOpen(false); settingsButton.current?.focus(); }
        }}>
        <label className="header-field match-field"><span className="setting-label">Match</span>
        <select value={name ?? ""} onChange={(e) => { setName(e.target.value); setSeekTo(0); setFollow(null); setSettingsOpen(false); }} aria-label="Match">
          {matches.map((m) => <option key={m.name} value={m.name}>{m.kind === "video" ? `${m.home.name} v ${m.away.name} · real footage` : `${m.home.name} v ${m.away.name} (${m.name.split("-")[0]})`}</option>)}
        </select>
        </label>
        <label className="header-field"><span className="setting-label">Language</span>
        <select value={actualLanguage} onChange={(e) => commit({ ...p, lang: e.target.value })} aria-label="Language">
          {Object.entries(languages).map(([code, label]) => <option key={code} value={code}>{label}</option>)}
        </select>
        </label>
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
        <button className={`profile-chip${accent ? " fav" : ""}`} onClick={() => { setSettingsOpen(false); setPicker("edit"); }} aria-label="Edit your profile"
                title={clubAbsent ? "Your club isn't playing in this match" : "Edit your profile"}>
          {chip}{clubAbsent && " (not in this match)"}
        </button>
        <ThemeSwitch />
        {!embedded && <a className="compare" href={compareHref} target="_blank" rel="noreferrer" title="Open two viewers of this match side by side">Compare viewers</a>}
        </div>
      </header>

      <main>
        <section className="stage">
          {welcome && !embedded && <section className="welcome" aria-labelledby="welcome-title">
            <div><h2 id="welcome-title">See the match. Understand the moment.</h2>
              <p>Try a favourite player, live ratings and explanations backed by match evidence. Personalisation is optional.</p></div>
            <div className="welcome-actions">
              <button type="button" className="primary" onClick={watchDemo} disabled={!matches.some((m) => m.kind !== "video")}>Watch demo</button>
              <button type="button" onClick={() => { setWelcome(false); setPicker("edit"); }}>Personalise</button>
              <button type="button" onClick={() => setWelcome(false)} aria-label="Dismiss welcome">Dismiss</button>
            </div>
          </section>}
          <div className="controls" role="group" aria-label="Replay controls">
            <div className="playback-state">
              {status === "paused" ? <button onClick={resume}>Play</button> : <button onClick={pause} disabled={status !== "live"}>Pause</button>}
              <span className="playback-clock" aria-label="Current match time">{simulationMode ? status === "ended" ? "Prototype ended" : mmss(clipT ?? 0) : showingClip ? mmss(clipT ?? clip?.clip.start ?? 0) : state?.finished ? "Full time" : state?.clock ?? "0′"}</span>
            </div>
            <div className="segmented" role="group" aria-label="Speed">
              {speeds.map((s) => <button key={s} className={speed === s ? "on" : ""} onClick={() => setSpeed(s)}>{s}×</button>)}
            </div>
            <ReplaySeek key={name} value={seekTo} max={simulationMode ? Math.floor(meta?.tracking?.duration ?? 360) : clipMode ? Math.floor(clip?.clip.duration ?? 99) : 90}
                        unit={clipMode || simulationMode ? "second" : "minute"} onChange={setSeekTo}
                        inputLabel={simulationMode ? "Seconds into exhibition" : undefined}
                        positionLabel={clipMode ? mmss((clip?.clip.start ?? 0) + seekTo) : simulationMode ? mmss(seekTo) : `${seekTo} minutes`}
                        onSeek={(value) => { clearHistory(); if (clipMode || simulationMode) seekAt(value); else seek(value); }} />
            {status === "ended" && <button type="button" onClick={() => {
              setSeekTo(0); clearHistory(); restart();
            }}>{clipMode ? "Replay the clip" : "Replay match"}</button>}
          </div>
          {simulationMode && <section className="welcome" aria-label="Simulation prototype">
            <div><h2>Every player. Every movement.</h2><p>Six-minute experimental simulation. All 22 players and the ball update five times a second. Tap a player to follow their movement. Try 1× or 2×.</p>
            <p>Passes and tackles use player positions. Marking, supporting runs and restarts are simulated.</p>
            {position && <p className="phase-label">{({ kickoff: "Preparing a kick-off", goal_kick: "Preparing a goal kick", keeper_ball: "Goalkeeper holding the ball", open_play: "Open play" } as Record<string, string>)[position.phase] ?? position.phase}</p>}</div>
            {follow && <button onClick={() => setFollow(null)}>Return to favourite</button>}
          </section>}
          {showingClip && meta && <ClipBanner meta={meta} info={clip} t={clipT} colours={colours} tracking={trackingView} />}
          {showingClip && follow && <ClipPinned stats={trackingView.players.find((x) => x.id === follow)} id={follow} colours={colours}
                                                events={clipEvents} info={clip} onStop={() => setFollow(null)} />}
          {showingMatch && meta && <Scoreboard meta={meta} state={state} colours={colours} clock={simulationMode ? mmss(clipT ?? 0) : undefined} />}
          {showingMatch && meta && <FocusStrip meta={meta} state={state} colours={colours} focus={p.focus} />}
          {showingMatch && meta && pinned && <PinnedPlayer state={state} meta={meta} colours={colours} playerId={pinned.id} mode={p.mode} focus={p.focus}
                                           history={ratingHistory} onChange={() => setPicker("edit")} />}
          {(showingClip || (showingMatch && simulationMode)) && <section className="pitch-tools" aria-label="Pitch layers">
            <div className="segmented" role="group" aria-label="Surface view">
              <button type="button" aria-pressed={surfaceView === "current"} className={surfaceView === "current" ? "on" : ""} onClick={() => setSurfaceView("current")}>Current play</button>
              <button type="button" aria-pressed={surfaceView === "history"} className={surfaceView === "history" ? "on" : ""} onClick={() => setSurfaceView("history")}>Activity history</button>
            </div>
            <label><input type="checkbox" checked={showTrail} disabled={!spotlit} onChange={(e) => setShowTrail(e.target.checked)} /> Player trail</label>
            <label><input type="checkbox" checked={showNearby} disabled={!spotlit} onChange={(e) => setShowNearby(e.target.checked)} /> Nearby players</label>
            <label>Camera <select aria-label="Camera view" value={cameraMode} onChange={(e) => setCameraMode(e.target.value as CameraMode)}>
              <option value="full">Full pitch</option><option value="ball">Follow ball</option>
              <option value="player" disabled={!spotlit}>Follow player</option>
              {cameraMode === "manual" && <option value="manual">Manual view</option>}
            </select></label>
            <p>{spotlit ? `${showTrail ? "Trail: up to eight seconds. Tracking gaps break the trail. " : ""}${showNearby ? "Nearby: players within 12 metres, in team colours." : ""}` : "Tap a player to reveal their recent path and nearby players."}</p>
          </section>}
          {(showingMatch || showingClip) && <p className="pitch-caption">
            {simulationMode ? "Simulated positions · 22 players · 5 updates/s" : showingClip ? "Real footage: tracked positions" : "Synthetic match replay"} · {speed}× speed · Surface: {(showingClip || simulationMode) && surfaceView === "current" ? "recent movement and ball" : "activity history"}
          </p>}
          <div className="pitch" ref={pitchEl}>
            {spotlit && <div className="spot-label" ref={spotLabel} style={{ borderColor: spotlit.colour }}>
              {followed ? `★ ${trackLabel(followed.id)}` : pinned && `#${pinned.number} ${pinned.name.split(" ").slice(-1)[0]}`}</div>}
            {meta && <Overlays cues={cues} meta={meta} mode={p.mode} colours={colours} />}
            {status === "connecting" && <div className="overlay-msg">Connecting to the replay server…</div>}
            {status === "error" && <div className="overlay-msg">Can't reach the replay server. {import.meta.env.DEV ? "Is it running on port 8000?" : "It may be waking up: try again in a moment."}</div>}
            {status === "disconnected" && <div className="overlay-msg">Lost the connection to the replay server. Pick a minute and press Go to reconnect.</div>}
          </div>
          {showingMatch && <>
            <div className="desktop-momentum"><MomentumChart state={state} colours={colours} /></div>
            <details className="mobile-momentum"><summary>Match momentum</summary><MomentumChart state={state} colours={colours} /></details>
          </>}
          {showingClip && clip && <ClipCredit info={clip} />}
          <details className="pitch-guide"><summary>How to read the pitch</summary>
          {showingClip ? (
            <p className="legend">
              Each marker is one tracked person: {meta?.home.name} in blue, {meta?.away.name} in white, grey where the model could not tell
              the team. The number is the tracker's ID, not a shirt number; tap a marker to follow that player. Lines are detected passes and
              carries, a ring is an interception. The ball shows only where the video found it. The surface rises where each side's
              players have been. Current play follows recent movement and the ball; Activity history keeps the longer view.
              Select a player to show their last eight seconds of movement and highlight players within 12 metres.
              Gaps in detection break the path. Drag to turn the pitch, scroll to zoom, double-click to reset.
            </p>
          ) : simulationMode ? (
            <p className="legend">Each numbered marker is a simulated player wearing their shirt number. Tap any player to follow them.
              The ball moves between players; lines show passes and carries. Current play follows recent movement and the ball;
              Activity history keeps the longer view. Player trail shows the last eight seconds, and Nearby players highlights those within 12 metres.
              Drag to turn the pitch, scroll to zoom, double-click to reset.</p>
          ) : (
            <p className="legend">
              The surface rises where each team has been active in the last two minutes, coloured by which team owns that space.
              Spikes are shots: the taller, the better the chance. Goals glow. Dots trace the ball's last few touches, in the colour of
              the team that played it. Drag to turn the pitch, scroll to zoom, double-click to reset.
              {pinned && " The ring follows your player: it sits where they last touched the ball."}
            </p>
          )}
          </details>
        </section>

        {layout === "fan" && meta && (showingClip || showingMatch) && <aside aria-label="Match details">
          <nav className="mobile-panel-tabs" aria-label="Match panels">
            {panels.map((value) => (
              <button type="button" key={value} className={activePanel === value ? "on" : ""} aria-pressed={activePanel === value}
                      onClick={() => setPanel(value)}>
                {value === "moments" ? "Moments" : value === "players" ? "Players" : showingClip ? "About clip" : "Stats"}
              </button>
            ))}
          </nav>
          <div className="detail-section" data-active={activePanel === "moments"}>
            <MomentFeed moments={moments} meta={meta} aiInfo={aiInfo} mode={p.mode} colours={colours} allTiers={!!showingClip || simulationMode} follow={showingClip ? follow : null}
              onSeek={!controlled && (showingClip || simulationMode) ? (time) => {
                const seconds = Math.max(0, time - (showingClip ? clip?.clip.start ?? 0 : 0));
                setSeekTo(Math.floor(seconds)); clearHistory(); seekAt(seconds); resume();
              } : undefined} />
          </div>
          <div className="detail-section" data-active={activePanel === "players"}>
            {showingClip ? <ClipPlayers tracking={trackingView} colours={colours} follow={follow} setFollow={setFollow} /> :
              <Ratings state={state} meta={meta} colours={colours} favourite={inspected} setFavourite={setInspected}
                       followed={simulationMode ? pinned?.id ?? null : p.player} onFollow={(id) => {
                         if (simulationMode) setFollow(id);
                         else if (id !== p.player) commit({ ...p, player: id });
                       }} />}
          </div>
          <div className="detail-section" data-active={activePanel === "stats"}>
          {simulationMode && <PositionInsights meta={meta} position={position} />}
          {showingClip ? <>
          {p.mode === "analyst" && <ClipEvents events={clipEvents} mode={p.mode} colours={colours} meta={meta} info={clip} follow={follow} />}
          {clip && <ClipPanel info={clip} lang={p.lang} />}
          </> : p.mode === "analyst" && <StatsPanel state={state} meta={meta} focus={p.focus} />}
          </div>
        </aside>}
      </main>

      {picker && <ProfilePicker clubs={clubs} languages={languages} profile={p} fromLink={fromLink} fallbackFocus={appTitle.current} clipMode={!!showingClip}
                                onSave={(next) => { commit(next); setWelcome(false); setPicker(null); }} onReset={reset} onClose={() => setPicker(null)} />}
    </div>
  );
}
