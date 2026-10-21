import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MomentFeed, MomentumChart, Ratings, Scoreboard, StatsPanel } from "./components/Panels";
import { PitchScene, teamColours } from "./pitch/PitchScene";
import type { MatchEvent, MatchMeta, MatchSummary, Moment, ViewMode } from "./types";
import { useReplay } from "./useReplay";

const SPEEDS = [1, 5, 20, 60];

export default function App() {
  const [matches, setMatches] = useState<MatchSummary[]>([]);
  const [name, setName] = useState<string | null>(null);
  const [mode, setMode] = useState<ViewMode>("analyst");
  const [favourite, setFavourite] = useState<string | null>(null);
  const [seekTo, setSeekTo] = useState(0);
  const sceneRef = useRef<PitchScene | null>(null);
  const pitchEl = useRef<HTMLDivElement>(null);
  const firstHalfEnd = useRef<number | null>(null);

  useEffect(() => {
    fetch("/api/matches").then((r) => r.json()).then((list: MatchSummary[]) => {
      setMatches(list);
      if (list.length) setName(list[0].name);
    }).catch(() => setMatches([]));
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

  const { meta, state, moments, liveMoment, status, speed, setSpeed, pause, resume, seek } = useReplay(name, onEvent, onReset);

  useEffect(() => {
    if (meta) sceneRef.current?.setMatch(meta);
    setFavourite(null);
  }, [meta]);

  const colours = useMemo<[string, string]>(() => {
    if (!meta) return ["#4f7cff", "#ff5a5a"];
    const [h, a] = teamColours(meta);
    return [`#${h.getHexString()}`, `#${a.getHexString()}`];
  }, [meta]);

  const banner = useLowerThird(liveMoment);

  return (
    <div className="app">
      <header>
        <h1>Pitch Insights <small>live football intelligence</small></h1>
        <select value={name ?? ""} onChange={(e) => setName(e.target.value)} aria-label="Match">
          {matches.map((m) => <option key={m.name} value={m.name}>{m.home.name} v {m.away.name} ({m.name.split("-")[0]})</option>)}
        </select>
        <div className="segmented" role="group" aria-label="Viewer mode">
          {(["casual", "analyst"] as ViewMode[]).map((v) => (
            <button key={v} className={mode === v ? "on" : ""} onClick={() => setMode(v)}>{v === "casual" ? "Casual fan" : "Analyst"}</button>
          ))}
        </div>
      </header>

      <main>
        <section className="stage">
          {meta && <Scoreboard meta={meta} state={state} colours={colours} />}
          <div className="pitch" ref={pitchEl}>
            {banner && (
              <div className={`lowerthird ${banner.tier}`} key={banner.id}>
                <span className="lt-clock">{banner.clock}</span>
                <span className="lt-head">{banner.headline}</span>
                {mode === "analyst" && banner.facts[1] && <span className="lt-fact">{banner.facts[1].text}</span>}
              </div>
            )}
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
          </p>
        </section>

        <aside>
          {meta && <MomentFeed moments={moments} meta={meta} mode={mode} colours={colours} />}
          {meta && <Ratings state={state} meta={meta} colours={colours} favourite={favourite} setFavourite={setFavourite} />}
          {meta && mode === "analyst" && <StatsPanel state={state} meta={meta} />}
        </aside>
      </main>
    </div>
  );
}

/** The latest headline moment that arrived live, shown over the pitch for a few seconds. */
function useLowerThird(live: Moment | null) {
  const [banner, setBanner] = useState<Moment | null>(null);
  useEffect(() => {
    if (!live) setBanner(null);
    else if (live.tier === "headline") setBanner(live);
  }, [live]);
  // The timer belongs to the banner, so a smaller moment arriving meanwhile can't cancel it.
  useEffect(() => {
    if (!banner) return;
    const t = setTimeout(() => setBanner(null), 6000);
    return () => clearTimeout(t);
  }, [banner]);
  return banner;
}
