import { useCallback, useEffect, useRef, useState } from "react";
import type { CommentaryInfo, LiveState, MatchEvent, MatchMeta, Moment } from "./types";

export type Status = "connecting" | "live" | "paused" | "ended" | "disconnected" | "error";

/**
 * Connects to the replay server for one match and keeps the latest state.
 * Events go to `onEvent` (for the 3D pitch) instead of React state, so a busy
 * match doesn't re-render the page on every pass.
 */
export function useReplay(name: string | null, onEvent: (ev: MatchEvent, meta: MatchMeta) => void,
                          onReset: () => void) {
  const [meta, setMeta] = useState<MatchMeta | null>(null);
  const [aiInfo, setAiInfo] = useState<CommentaryInfo | null>(null);
  const [state, setState] = useState<LiveState | null>(null);
  const [moments, setMoments] = useState<Moment[]>([]);
  // The latest moment that arrived live, not from a catch-up, for the banner over the pitch.
  const [liveMoment, setLiveMoment] = useState<Moment | null>(null);
  const [status, setStatus] = useState<Status>("connecting");
  const [speed, setSpeedState] = useState(20);
  // A jump belongs to the match it was made in; `n` makes a repeat jump to the same minute reconnect.
  const [jump, setJump] = useState<{ match: string | null; minute: number; n: number }>({ match: null, minute: 0, n: 0 });
  const from = jump.match === name ? jump.minute : 0;
  const ws = useRef<WebSocket | null>(null);
  const metaRef = useRef<MatchMeta | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const onResetRef = useRef(onReset);
  onResetRef.current = onReset;
  const speedRef = useRef(speed);
  speedRef.current = speed;

  useEffect(() => {
    if (!name) return;
    setStatus("connecting");
    setMoments([]);
    setLiveMoment(null);
    setState(null);
    onResetRef.current();
    let ended = false;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${proto}://${location.host}/ws/replay/${name}?speed=${speedRef.current}&from=${from}`);
    ws.current = socket;
    socket.onmessage = (msg) => {
      const data = JSON.parse(msg.data);
      switch (data.type) {
        case "meta":
          metaRef.current = data.meta;
          setMeta(data.meta);
          setAiInfo(data.commentary ?? null);
          setStatus("live");
          break;
        case "catchup":
          setMoments(data.moments);
          setState(data.state);
          if (metaRef.current) for (const ev of data.recent_events ?? []) onEventRef.current(ev, metaRef.current);
          break;
        case "event":
          if (metaRef.current) onEventRef.current(data.event, metaRef.current);
          break;
        case "moment":
          setMoments((m) => [...m, data.moment]);
          setLiveMoment(data.moment);
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
    socket.onerror = () => { ended = true; setStatus("error"); };
    socket.onclose = () => { if (!ended) setStatus("disconnected"); };
    return () => {
      ended = true; // closing on purpose (new match or jump), not a lost connection
      socket.close();
    };
  }, [name, from, jump.n]);

  const send = (cmd: object) => ws.current?.readyState === WebSocket.OPEN && ws.current.send(JSON.stringify(cmd));

  const setSpeed = useCallback((value: number) => {
    setSpeedState(value);
    send({ cmd: "speed", value });
  }, []);
  const pause = useCallback(() => { send({ cmd: "pause" }); setStatus("paused"); }, []);
  const resume = useCallback(() => { send({ cmd: "resume" }); setStatus("live"); }, []);
  const seek = useCallback((minute: number) => setJump((j) => ({ match: name, minute, n: j.n + 1 })), [name]);

  return { meta, aiInfo, state, moments, liveMoment, status, speed, from, setSpeed, pause, resume, seek };
}
