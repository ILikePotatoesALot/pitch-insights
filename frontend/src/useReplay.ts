import { useCallback, useEffect, useRef, useState } from "react";
import { connectionParams } from "./profile";
import type { ClipEventLine, ClipFrame, ClipInfo, CommentaryInfo, Cue, LiveState, MatchEvent, MatchMeta, Moment, Profile } from "./types";

export type Status = "connecting" | "live" | "paused" | "ended" | "disconnected" | "error";

/**
 * Connects to the replay server for one match and keeps the latest state.
 * Events go to `onEvent` (for the 3D pitch) instead of React state, so a busy
 * match doesn't re-render the page on every pass.
 */
export function useReplay(name: string | null, profile: Profile, defaultSpeed: number, onEvent: (ev: MatchEvent, meta: MatchMeta) => void,
                          onReset: () => void, onFrame: (frame: ClipFrame, meta: MatchMeta) => void = () => {}) {
  const { lang, mode, team, player, focus } = profile;
  const [meta, setMeta] = useState<MatchMeta | null>(null);
  const [aiInfo, setAiInfo] = useState<CommentaryInfo | null>(null);
  // Languages the server has stored translations for (code -> name), English always first.
  const [languages, setLanguages] = useState<Record<string, string>>({ en: "English" });
  const [state, setState] = useState<LiveState | null>(null);
  const [moments, setMoments] = useState<Moment[]>([]);
  // The overlays on screen right now. The server starts and ends each one (the Overlay Director), so a
  // pause freezes them and a seek or reconnect starts with a clear screen.
  const [cues, setCues] = useState<Cue[]>([]);
  const [status, setStatus] = useState<Status>("connecting");
  // The speed belongs to the match it was chosen in, so another match starts at its own default (a clip of
  // real footage plays at 1x, a synthetic match at 20x).
  const [chosen, setChosen] = useState<{ match: string | null; value: number }>({ match: null, value: 0 });
  const speed = chosen.match === name ? chosen.value : defaultSpeed;
  // The video clip: what the credibility panel shows, the events detected so far (in the viewer's language),
  // and how far in the replay is (whole seconds into the half, so the page re-renders once a second, not per frame).
  const [clip, setClip] = useState<ClipInfo | null>(null);
  const [clipEvents, setClipEvents] = useState<ClipEventLine[]>([]);
  const [clipT, setClipT] = useState<number | null>(null);
  // A jump belongs to the match it was made in; `n` makes a repeat jump to the same minute reconnect.
  // `at` is exact match seconds (it wins over `minute`), for a reconnect that must land on the same
  // second: a broadcast minute can't say first-half stoppage time (45+2').
  const [jump, setJump] = useState<{ match: string | null; minute: number; at: number | null; n: number }>(
    { match: null, minute: 0, at: null, n: 0 });
  const from = jump.match === name ? jump.minute : 0;
  const at = jump.match === name ? jump.at : null;
  const ws = useRef<WebSocket | null>(null);
  const metaRef = useRef<MatchMeta | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const onResetRef = useRef(onReset);
  onResetRef.current = onReset;
  const onFrameRef = useRef(onFrame);
  onFrameRef.current = onFrame;
  const speedRef = useRef(speed);
  speedRef.current = speed;
  // Paused by the viewer, and the profile the open connection uses: a change of language, club, player or focus
  // metric reconnects (the server's Director works from the profile it was given), and a paused replay should
  // stay paused through it.
  const pausedRef = useRef(false);
  const profileKeyRef = useRef<string | null>(null);
  // The viewer's profile goes to the server with the connection, so its Overlay Director keeps clean the screen
  // this viewer sees (cues made for analysts only don't take slots on a casual fan's screen) and favours their
  // club and player. Mode can also change without a reconnect (the `detail` command).
  const modeRef = useRef(mode);
  modeRef.current = mode;

  useEffect(() => {
    if (!name) return;
    setStatus("connecting");
    setMoments([]);
    setCues([]);
    setState(null);
    setAiInfo(null);
    setClipEvents([]);
    setClipT(null);
    onResetRef.current();
    const key = [lang, team, player, focus].join("|");
    const keepPaused = pausedRef.current && profileKeyRef.current !== null && profileKeyRef.current !== key;
    profileKeyRef.current = key;
    pausedRef.current = keepPaused;
    let ended = false;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${proto}://${location.host}/ws/replay/${name}?speed=${speedRef.current}&from=${from}${at === null ? "" : `&at=${at}`}&${connectionParams({ ...profile, mode: modeRef.current })}`);
    ws.current = socket;
    socket.onmessage = (msg) => {
      const data = JSON.parse(msg.data);
      switch (data.type) {
        case "meta":
          metaRef.current = data.meta;
          setMeta(data.meta);
          setAiInfo(data.commentary ?? null);
          setClip(data.kind === "video" ? data.clip : null);
          setLanguages(data.languages ?? { en: "English" });
          socket.send(JSON.stringify({ cmd: "detail", value: modeRef.current }));
          if (keepPaused) socket.send(JSON.stringify({ cmd: "pause" }));
          setStatus(keepPaused ? "paused" : "live");
          break;
        case "catchup":
          if (data.events) { // a clip: the events before the jump, for the feed
            setClipEvents(data.events);
            break;
          }
          setMoments(data.moments);
          setState(data.state);
          if (metaRef.current) for (const ev of data.recent_events ?? []) onEventRef.current(ev, metaRef.current);
          break;
        case "frame":
          if (metaRef.current) onFrameRef.current(data, metaRef.current);
          setClipT(Math.floor(data.t));
          break;
        case "event":
          if (data.text !== undefined) setClipEvents((e) => [...e, { event: data.event, text: data.text }]);
          if (metaRef.current) onEventRef.current(data.event, metaRef.current);
          break;
        case "moment":
          setMoments((m) => [...m, data.moment]);
          break;
        case "cue":
          setCues((c) => [...c.filter((x) => x.id !== data.cue.id), data.cue]);
          break;
        case "cue_end":
          setCues((c) => c.filter((x) => x.id !== data.id));
          break;
        case "state":
          setState(data.state);
          break;
        case "end":
          ended = true;
          setStatus("ended");
          break;
        case "error":
          ended = true;
          setStatus("error");
          break;
      }
    };
    socket.onerror = () => { ended = true; setStatus("error"); setCues([]); };
    socket.onclose = () => { if (!ended) { setStatus("disconnected"); setCues([]); } };
    return () => {
      ended = true; // closing on purpose (new match or jump), not a lost connection
      socket.close();
    };
  }, [name, from, jump.n, lang, team, player, focus]);

  const send = (cmd: object) => ws.current?.readyState === WebSocket.OPEN && ws.current.send(JSON.stringify(cmd));

  useEffect(() => { send({ cmd: "detail", value: mode }); }, [mode]);

  const setSpeed = useCallback((value: number) => {
    setChosen({ match: name, value });
    send({ cmd: "speed", value });
  }, [name]);
  const pause = useCallback(() => { send({ cmd: "pause" }); pausedRef.current = true; setStatus("paused"); }, []);
  const resume = useCallback(() => { send({ cmd: "resume" }); pausedRef.current = false; setStatus("live"); }, []);
  const seek = useCallback((minute: number) => setJump((j) => ({ match: name, minute, at: null, n: j.n + 1 })), [name]);
  const seekAt = useCallback((seconds: number) => setJump((j) => ({ match: name, minute: 0, at: seconds, n: j.n + 1 })), [name]);

  return { meta, aiInfo, languages, state, moments, cues, status, speed, from, setSpeed, pause, resume, seek, seekAt,
           clip, clipEvents, clipT };
}
