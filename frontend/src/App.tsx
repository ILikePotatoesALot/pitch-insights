import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Overlays } from "./components/Overlays";
import { MomentFeed, MomentumChart, Ratings, Scoreboard, StatsPanel } from "./components/Panels";
import { PitchScene, teamColours } from "./pitch/PitchScene";
import type { LayoutMode, MatchEvent, MatchMeta, MatchSummary, ViewMode } from "./types";
import { useReplay } from "./useReplay";

const SPEEDS = [1, 5, 20, 60];

export default function App() {
  const [matches, setMatches] = useState<MatchSummary[]>([]);
  const [name, setName] = useState<string | null>(null);
  const [mode, setMode] = useState<ViewMode>("analyst");
  const [layout, setLayout] = useState<LayoutMode>("fan");
  const [favourite, setFavourite] = useState<string | null>(null);
  const [lang, setLang] = useState("en");
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

  const { meta, aiInfo, languages, state, moments, cues, status, speed, setSpeed, pause, resume, seek, seekAt } =
    useReplay(name, lang, mode, onEvent, onReset);
  // A new language reconnects from the current moment (not the start of the minute, so nothing replays).
  // It goes by match seconds, because a minute can't say first-half stoppage time (45+2'). Before the first
  // state arrives there is no current moment, so the reconnect keeps the jump already made.
  const changeLang = (l: string) => {
    if (state?.period === 1) seekAt(state.match_minute * 60);
    else if (state) seekAt((firstHalfEnd.current ?? 2700) + (state.match_minute - 45) * 60);
    setLang(l);
  };

  useEffect(() => {
    if (meta) sceneRef.current?.setMatch(meta);
    setFavourite(null);
  }, [meta]);

  const colours = useMemo<[string, string]>(() => {
    if (!meta) return ["#4f7cff", "#ff5a5a"];
    const [h, a] = teamColours(meta);
    return [`#${h.getHexString()}`, `#${a.getHexString()}`];
  }, [meta]);

  return (
    <div className={`app ${layout}`}>
      <header>
        <h1>Pitch Insights <small>live football intelligence</small></h1>
        <select value={name ?? ""} onChange={(e) => setName(e.target.value)} aria-label="Match">
          {matches.map((m) => <option key={m.name} value={m.name}>{m.home.name} v {m.away.name} ({m.name.split("-")[0]})</option>)}
        </select>
        <select value={lang} onChange={(e) => changeLang(e.target.value)} aria-label="Language">
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
            <button key={v} className={mode === v ? "on" : ""} onClick={() => setMode(v)}>{v === "casual" ? "Casual fan" : "Analyst"}</button>
          ))}
        </div>
      </header>

      <main>
        <section className="stage">
          {meta && <Scoreboard meta={meta} state={state} colours={colours} />}
          <div className="pitch" ref={pitchEl}>
            {meta && <Overlays cues={cues} meta={meta} mode={mode} colours={colours} />}
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

        {layout === "fan" && <aside>
          {meta && <MomentFeed moments={moments} meta={meta} aiInfo={aiInfo} mode={mode} colours={colours} />}
          {meta && <Ratings state={state} meta={meta} colours={colours} favourite={favourite} setFavourite={setFavourite} />}
          {meta && mode === "analyst" && <StatsPanel state={state} meta={meta} />}
        </aside>}
      </main>
    </div>
  );
}
