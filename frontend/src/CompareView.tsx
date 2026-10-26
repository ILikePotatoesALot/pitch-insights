import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ThemeSwitch } from "./components/ThemeSwitch";
import { LANGUAGE_NAMES, profileFromUrl } from "./profile";
import type { ReplayCommand, ReplayReady } from "./useReplay";

// Each pane keeps its own profile and commentary. The parent coordinates their replay clocks.
const PRESETS = {
  a: "team=POT&player=POT-11&mode=casual&lang=de&focus=win_probability&layout=broadcast",
  b: "team=CAR&player=CAR-10&mode=analyst&lang=en&focus=xt_added&layout=broadcast",
};
type Ready = ReplayReady & { received: number };
type PaneMessage = { type: "ready"; epoch: number; ready: ReplayReady } | { type: "ended" | "fault"; epoch: number };

export default function CompareView() {
  const q = useMemo(() => new URLSearchParams(location.search), []);
  const own = useMemo(() => (["a", "b"] as const).map((side) => {
    const preset = q.get("match") === "continuous-prototype" && side === "a"
      ? PRESETS.a.replace("POT-11", "POT-07").replace("lang=de", "lang=en") : PRESETS[side];
    return new URLSearchParams(q.get(side) ?? preset);
  }), [q]);
  const initialSpeed = Number(q.get("speed"));
  const [speed, setSpeed] = useState([0.5, 1, 2, 5, 20, 60].includes(initialSpeed) ? initialSpeed : 20);
  const [loadSpeed, setLoadSpeed] = useState(speed);
  const [loadedKind, setLoadedKind] = useState<"synthetic" | "video">("synthetic");
  const [loadedTracking, setLoadedTracking] = useState(false);
  const [minute, setMinute] = useState(0);
  const [jumpTo, setJumpTo] = useState(0);
  const [epoch, setEpoch] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [waiting, setWaiting] = useState(true);
  const [ended, setEnded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [readies, setReadies] = useState<[Ready | null, Ready | null]>([null, null]);
  const frames = useRef<(HTMLIFrameElement | null)[]>([]);
  const playingRef = useRef(playing);
  playingRef.current = playing;
  const speedRef = useRef(speed);
  speedRef.current = speed;
  const epochRef = useRef(epoch);
  epochRef.current = epoch;
  const readiesRef = useRef(readies);
  readiesRef.current = readies;

  const dispatch = useCallback((action: ReplayCommand) => {
    frames.current.forEach((frame) => frame?.contentWindow?.postMessage({ type: "seize:command", epoch: epochRef.current, action }, location.origin));
  }, []);
  const wallAfter = useCallback((items: [Ready | null, Ready | null]) => {
    const now = performance.now();
    return Math.max(...items.filter((r): r is Ready => r !== null).map((r) => r.server_time + (now - r.received) / 1000)) + 0.4;
  }, []);

  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.origin !== location.origin) return;
      const index = frames.current.findIndex((frame) => frame?.contentWindow === event.source);
      if (index < 0) return;
      const message = event.data as PaneMessage;
      if (message?.epoch !== epochRef.current) return;
      if (message.type === "ready") {
        const next = [...readiesRef.current] as [Ready | null, Ready | null];
        if (next[index]) return;
        next[index] = { ...message.ready, received: performance.now() };
        readiesRef.current = next;
        setReadies(next);
        if (next[0] && next[1]) {
          if ((next[0].kind === "video" || next[0].tracking) && ![0.5, 1, 2, 5].includes(speedRef.current)) {
            setSpeed(1);
            dispatch({ cmd: "speed", value: 1, wall: wallAfter(next) });
          }
          setWaiting(false);
          if (playingRef.current) dispatch({ cmd: "resume", wall: wallAfter(next) });
        }
      } else if (message.type === "ended") {
        setEnded(true);
        setPlaying(false);
      } else if (message.type === "fault") {
        playingRef.current = false;
        dispatch({ cmd: "pause" });
        setPlaying(false);
        setFailed(true);
        setWaiting(false);
      }
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, [dispatch, wallAfter]);

  const reload = (target: number) => {
    setMinute(target);
    setJumpTo(target);
    setLoadSpeed(speed);
    setLoadedKind(kind);
    setLoadedTracking(simulation);
    readiesRef.current = [null, null];
    setReadies([null, null]);
    setWaiting(true);
    setEnded(false);
    setFailed(false);
    setEpoch((n) => n + 1);
  };
  const toggle = () => {
    if (waiting || ended || failed) return;
    dispatch({ cmd: playing ? "pause" : "resume", wall: wallAfter(readiesRef.current) });
    setPlaying(!playing);
  };
  const changeSpeed = (value: number) => {
    setSpeed(value);
    if (!waiting && !ended && !failed) dispatch({ cmd: "speed", value, wall: wallAfter(readiesRef.current) });
  };
  const kind = readies[0]?.kind ?? "synthetic";
  const simulation = readies[0]?.tracking ?? loadedTracking;
  const seconds = kind === "video" || simulation;
  const limit = kind === "video" ? Math.floor(readies[0]?.duration ?? 99) : simulation ? Math.floor(readies[0]?.duration ?? 360) : 90;
  const names = own.map((pane, index) => {
    const profile = profileFromUrl(`?${pane}`);
    const lang = readies[index]?.lang ?? profile?.lang ?? "en";
    return `Viewer ${index ? "B" : "A"} · ${profile?.mode === "casual" ? "Casual fan" : "Analyst"} · ${LANGUAGE_NAMES[lang] ?? lang}`;
  });
  const panes = own.map((pane) => {
    const url = new URLSearchParams(pane);
    url.delete("match");
    url.set("embed", "1");
    url.set("sync", String(epoch));
    url.set("speed", String(loadSpeed));
    if (q.has("match")) url.set("match", q.get("match")!);
    if (loadedKind === "video" || loadedTracking) url.set("at", String(minute));
    else url.set("from", String(minute));
    return `/?${url}`;
  });
  const single = new URLSearchParams(own[0]);
  if (q.has("match")) single.set("match", q.get("match")!);
  return (
    <div className="compare-page">
      <div className="compare-toolbar">
        <a href={`/?${single}`}>Watch one match</a>
        <div className="compare-controls">
          <button type="button" onClick={toggle} disabled={waiting || ended || failed}>{playing ? "Pause both" : "Play both"}</button>
          <label>Speed <select value={speed} disabled={waiting || failed} onChange={(e) => changeSpeed(Number(e.target.value))}>
            {(kind === "video" || simulation ? [0.5, 1, 2, 5] : [1, 5, 20, 60]).map((value) => <option key={value} value={value}>{value}×</option>)}
          </select></label>
          <label>Jump to <input type="number" min={0} max={limit} value={jumpTo} onChange={(e) => setJumpTo(Number(e.target.value))} aria-label={seconds ? "Replay second" : "Match minute"} />
            {seconds ? " s" : "′"}</label>
          <button type="button" onClick={() => reload(jumpTo)} disabled={waiting || !Number.isInteger(jumpTo) || jumpTo < 0 || jumpTo > limit}>Go</button>
          {ended && <button type="button" onClick={() => { setPlaying(true); reload(0); }}>Replay both</button>}
          {failed && <span role="alert">A viewer lost its connection. Press Go to reconnect both.</span>}
          {waiting && <span role="status">Preparing both viewers…</span>}
        </div>
        <ThemeSwitch />
      </div>
      <p className="compare-mobile-note">Two viewers is best on a larger screen. You can watch one match with all the same controls.</p>
      <div className="compare-view">
        {panes.map((src, i) => <div className="compare-pane" key={i}>
          <div className="compare-viewer-label">{names[i]}</div>
          <iframe key={epoch} ref={(node) => { frames.current[i] = node; }} src={src} title={names[i]} />
        </div>)}
      </div>
    </div>
  );
}
