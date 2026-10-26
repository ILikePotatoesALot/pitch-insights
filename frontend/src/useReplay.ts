import { useCallback, useEffect, useRef, useState } from "react";
import { wsUrl } from "./api";
import { connectionParams } from "./profile";
import type { ClipEventLine, ClipFrame, ClipInfo, CommentaryInfo, Cue, LiveState, MatchEvent, MatchMeta, Moment, Profile } from "./types";

export type Status = "connecting" | "live" | "paused" | "ended" | "disconnected" | "error";
export type ReplayCommand = { cmd: "pause" | "resume" | "speed"; value?: number; wall?: number };
export type ReplayReady = { server_time: number; kind: "synthetic" | "video"; duration?: number };
export type ReplayOptions = { controlled?: boolean; initialMinute?: number; initialAt?: number | null; onReady?: (ready: ReplayReady) => void };

/**
 * Connects to the replay server for one match and keeps the latest state.
 * Events go to `onEvent` (for the 3D pitch) instead of React state, so a busy
 * match doesn't re-render the page on every pass.
 */
export function useReplay(name: string | null, profile: Profile, defaultSpeed: number, onEvent: (ev: MatchEvent, meta: MatchMeta) => void,
                          onReset: () => void, onFrame: (frame: ClipFrame, meta: MatchMeta) => void = () => {},
                          onPositions: (events: MatchEvent[], meta: MatchMeta) => void = () => {}, options: ReplayOptions = {}) {
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
  const from = jump.match === name ? jump.minute : options.initialMinute ?? 0;
  const at = jump.match === name ? jump.at : options.initialAt ?? null;
  const ws = useRef<WebSocket | null>(null);
  const metaRef = useRef<MatchMeta | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const onResetRef = useRef(onReset);
  onResetRef.current = onReset;
  const onFrameRef = useRef(onFrame);
  onFrameRef.current = onFrame;
  const onPositionsRef = useRef(onPositions);
  onPositionsRef.current = onPositions;
  const speedRef = useRef(speed);
  speedRef.current = speed;
  const readyRef = useRef(options.onReady);
  readyRef.current = options.onReady;
  // Reconnecting within the same match preserves the viewer's pause, including a seek or profile change.
  // A different match and a replay after the end start playing normally.
  const pausedRef = useRef(false);
  const matchRef = useRef<string | null>(null);
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
    const keepPaused = options.controlled || (pausedRef.current && matchRef.current === name);
    matchRef.current = name;
    pausedRef.current = keepPaused;
    let ended = false;
    const socket = new WebSocket(wsUrl(`/ws/replay/${name}?speed=${speedRef.current}&from=${from}${at === null ? "" : `&at=${at}`}&${options.controlled ? "paused=1&" : ""}${connectionParams({ ...profile, mode: modeRef.current })}`));
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
          if (keepPaused && !options.controlled) socket.send(JSON.stringify({ cmd: "pause" }));
          setStatus(keepPaused ? "paused" : "live");
          break;
        case "ready":
          readyRef.current?.(data as ReplayReady);
          break;
        case "catchup":
          if (data.events) { // a clip: the events and moments before the jump, for the feeds
            setClipEvents(data.events);
            setMoments(data.moments ?? []);
            break;
          }
          setMoments(data.moments);
          setState(data.state);
          if (metaRef.current) onPositionsRef.current(data.position_events ?? [], metaRef.current);
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
          pausedRef.current = false;
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

  const command = useCallback((action: ReplayCommand) => {
    send(action);
    if (action.cmd === "speed" && action.value !== undefined) setChosen({ match: name, value: action.value });
    if (action.cmd === "pause") { pausedRef.current = true; setStatus("paused"); }
    if (action.cmd === "resume") { pausedRef.current = false; setStatus("live"); }
  }, [name]);
  const setSpeed = useCallback((value: number) => command({ cmd: "speed", value }), [command]);
  const pause = useCallback(() => command({ cmd: "pause" }), [command]);
  const resume = useCallback(() => command({ cmd: "resume" }), [command]);
  const seek = useCallback((minute: number) => setJump((j) => ({ match: name, minute, at: null, n: j.n + 1 })), [name]);
  const seekAt = useCallback((seconds: number) => setJump((j) => ({ match: name, minute: 0, at: seconds, n: j.n + 1 })), [name]);

  return { meta, aiInfo, languages, state, moments, cues, status, speed, from, setSpeed, pause, resume, command, seek, seekAt,
           clip, clipEvents, clipT };
}
