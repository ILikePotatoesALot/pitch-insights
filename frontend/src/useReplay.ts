import { useCallback, useEffect, useRef, useState } from "react";
import type { LiveState, MatchEvent, MatchMeta, Moment } from "./types";

export type Status = "connecting" | "live" | "paused" | "ended" | "error";

/**
 * Connects to the replay server for one match and keeps the latest state.
 * Events go to `onEvent` (for the 3D pitch) instead of React state, so a busy
 * match doesn't re-render the page on every pass.
 */
export function useReplay(name: string | null, onEvent: (ev: MatchEvent, meta: MatchMeta) => void,
                          onReset: () => void) {
  const [meta, setMeta] = useState<MatchMeta | null>(null);
  const [state, setState] = useState<LiveState | null>(null);
  const [moments, setMoments] = useState<Moment[]>([]);
  const [status, setStatus] = useState<Status>("connecting");
  const [speed, setSpeedState] = useState(20);
  const [from, setFrom] = useState(0);
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
    setState(null);
    onResetRef.current();
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${proto}://${location.host}/ws/replay/${name}?speed=${speedRef.current}&from=${from}`);
    ws.current = socket;
    socket.onmessage = (msg) => {
      const data = JSON.parse(msg.data);
      switch (data.type) {
        case "meta":
          metaRef.current = data.meta;
          setMeta(data.meta);
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
          break;
        case "state":
          setState(data.state);
          break;
        case "end":
          setStatus("ended");
          break;
        case "error":
          setStatus("error");
          break;
      }
    };
    socket.onerror = () => setStatus("error");
    return () => socket.close();
  }, [name, from]);

  const send = (cmd: object) => ws.current?.readyState === WebSocket.OPEN && ws.current.send(JSON.stringify(cmd));

  const setSpeed = useCallback((value: number) => {
    setSpeedState(value);
    send({ cmd: "speed", value });
  }, []);
  const pause = useCallback(() => { send({ cmd: "pause" }); setStatus("paused"); }, []);
  const resume = useCallback(() => { send({ cmd: "resume" }); setStatus("live"); }, []);
  const seek = useCallback((minute: number) => setFrom(minute), []);

  return { meta, state, moments, status, speed, from, setSpeed, pause, resume, seek };
}
