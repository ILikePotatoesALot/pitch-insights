import type { ClipTracking, TrackStats } from "../clipStats";
import type { ClipEventLine, ClipInfo, MatchMeta, ViewMode } from "../types";
import { trackLabel } from "../pitch/ClipLayer";

const pct = (v: number) => `${Math.round(v * 100)}%`;
const kmh = (ms: number) => `${Math.round(ms * 3.6)} km/h`;

/** Time into the half as the match clock shows it: 2280 s is 38:00. */
export const mmss = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t) % 60).padStart(2, "0")}`;

/**
 * The scoreboard for a clip: who is playing, that this is real footage (there is no score: the clip is 100 s of a
 * match), the clock, and in place of win probability, which side has had the ball, from the tracking.
 */
export function ClipBanner({ meta, info, t, colours, tracking }: {
  meta: MatchMeta; info: ClipInfo | null; t: number | null; colours: [string, string]; tracking: ClipTracking;
}) {
  const start = info?.clip.start ?? 0, length = info?.clip.duration ?? 1;
  const at = t === null ? start : t;
  const [l, r] = tracking.possession;
  const share = l + r ? l / (l + r) : null;
  return (
    <div className="scoreboard clip-banner">
      <div className="teams">
        <span className="team"><i style={{ background: colours[0] }} />{meta.home.name}</span>
        <span className="clip-tag" title="Positions measured from match video by a computer-vision model">Real footage</span>
        <span className="team away">{meta.away.name}<i style={{ background: colours[1] }} /></span>
      </div>
      <div className="clock">{mmss(at)} <small>first half · clip {info ? `${info.clip.from} to ${info.clip.to}` : ""}</small></div>
      <div className="winprob" title="Which side had a player nearest the ball (within 3 m), from the tracking, since you started watching">
        {share === null ? <div className="draw" style={{ width: "100%" }}>Possession appears once the ball is found</div> : <>
          <div style={{ width: pct(share), background: colours[0] }}>{share >= 0.2 ? `Possession ${pct(share)}` : share >= 0.1 && pct(share)}</div>
          <div style={{ width: pct(1 - share), background: colours[1] }}>{share <= 0.85 && pct(1 - share)}</div>
        </>}
      </div>
      <div className="clip-progress" aria-hidden="true"><div style={{ width: `${Math.min(100, Math.max(0, ((at - start) / length) * 100))}%` }} /></div>
    </div>
  );
}

/** One line under the controls, in every layout: that these positions are measured, how well, and from where. */
export function ClipCredit({ info }: { info: ClipInfo }) {
  const f = info.figures;
  return (
    <p className="clip-credit">
      <b>Positions measured from real match video</b> by {info.fine_tuned ? "RF-DETR small fine-tuned on SoccerTrack v2" : "RF-DETR small"}:{" "}
      {pct(f.precision)} precision, {pct(f.recall)} recall, {f.position_error_mean_m.toFixed(2)} m mean error on this clip.{" "}
      <a href={info.credit_url} target="_blank" rel="noreferrer">{info.credit}</a>
    </p>
  );
}

/**
 * Where the positions come from: the benchmark figures, the model, the credit and what the figures don't cover.
 * Folded away like a moment's "Why?", with the headline figures on the fold so they're always in view.
 */
export function ClipPanel({ info, lang }: { info: ClipInfo; lang: string }) {
  const f = info.figures;
  const rows: [string, string, string][] = [
    ["Precision", pct(f.precision), "tracked people that are real players"],
    ["Recall", pct(f.recall), "players found, within " + f.match_radius_m + " m"],
    ["Position error", `${f.position_error_mean_m.toFixed(2)} m`, `mean; median ${f.position_error_median_m.toFixed(2)} m, 90% within ${f.position_error_p90_m.toFixed(1)} m`],
    ["Team accuracy", pct(f.team_accuracy), "side read from shirt colour"],
  ];
  return (
    <details className="panel clip-panel">
      <summary>
        <h3>Why trust these positions? <small>{pct(f.precision)} precision · {f.position_error_mean_m.toFixed(2)} m error</small></h3>
      </summary>
      <p className="clip-lead">
        Real video of a university match, not a simulation. A computer-vision model looked for every player in each frame
        ({info.clip.fps} a second) and our tracker turned that into positions on the pitch, in metres.
      </p>
      <dl className="clip-figures">
        {rows.map(([label, value, note]) => (
          <div key={label}><dt>{label}</dt><dd>{value}</dd><dd className="note">{note}</dd></div>
        ))}
      </dl>
      <p className="clip-model"><b>Model:</b> {info.model}. {info.fine_tuned && "Fine-tuned on SoccerTrack v2 player boxes."} Scored against SoccerTrack's own labels on
        these {Math.round(info.clip.duration)} seconds ({info.clip.frames} frames).</p>
      <p className="clip-model"><b>Credit:</b> video and labels from <a href={info.credit_url} target="_blank" rel="noreferrer">{info.credit}</a>.
        Players are shown by side and tracker number only.</p>
      <details className="clip-limits">
        <summary>What these numbers don't cover</summary>
        <ul>{info.limits.map((l) => <li key={l}>{l}</li>)}</ul>
      </details>
      {lang !== "en" && <p className="ai-note">The wording of the detected events is translated by us; the labels and numbers are the same in every language.</p>}
    </details>
  );
}

/** The events the video path detected so far, newest first, with how sure it was. */
export function ClipEvents({ events, mode, colours, meta, info, follow }: {
  events: ClipEventLine[]; mode: ViewMode; colours: [string, string]; meta: MatchMeta; info: ClipInfo | null; follow: string | null;
}) {
  return (
    <div className="panel feed">
      <h3>Detected events <small>{mode === "casual" ? "passes, carries and interceptions" : "inferred from the ball and who was nearest"}</small></h3>
      {events.length === 0 ? <p className="empty">Nothing yet. Events appear here as the clip plays.</p> : (
        <ul>
          {[...events].reverse().map(({ event, text }) => {
            const colour = event.team_id === meta.home.id ? colours[0] : event.team_id === meta.away.id ? colours[1] : "var(--muted)";
            const mine = !!follow && (event.player_id === follow || event.receiver_id === follow);
            return (
              <li className={`moment${mine ? " mine" : ""}`} key={event.seq} style={{ borderLeftColor: colour }} title={event.player_id ? trackLabel(event.player_id) : undefined}>
                <div className="clip-event">
                  <span className="mclock">{mmss(event.t)}</span>
                  <span className="mhead">{mine && "★ "}{text}</span>
                  {mode === "analyst" && <span className="why">{pct(event.confidence)} sure</span>}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <p className="ai-note">The video path's own detections; the key moments are written from them.
        {info && ` Within five seconds of SoccerTrack's labels, ${pct(info.figures.event_precision)} of what it reports is real and it finds ${pct(info.figures.event_recall)} of the real events.`}</p>
    </div>
  );
}

/** The tracked players, like the live ratings: who has covered most ground and how fast, from the tracking. Tap to follow. */
export function ClipPlayers({ tracking, colours, follow, setFollow }: {
  tracking: ClipTracking; colours: [string, string]; follow: string | null; setFollow: (id: string | null) => void;
}) {
  const top = tracking.players.filter((p) => p.side !== null && p.seen).sort((a, b) => b.distance - a.distance).slice(0, 8);
  return (
    <div className="panel ratings clip-players">
      <h3>Players <small>from the tracking · tap one to follow</small></h3>
      {top.length === 0 ? <p className="empty">Players appear as the tracker finds them.</p> : <ol>
        {top.map((p) => (
          <li key={p.id} onClick={() => setFollow(p.id === follow ? null : p.id)} className={p.id === follow ? "active" : ""}>
            <i style={{ background: colours[p.side!] }} />
            <span className="pname">{p.id === follow && "★ "}{trackLabel(p.id)}</span>
            <small>top {kmh(p.topSpeed)}</small>
            <b>{Math.round(p.distance)} m</b>
          </li>
        ))}
      </ol>}
      <p className="ai-note">Distance covered and top speed since you started watching. Numbers are the tracker's, not shirt numbers.</p>
    </div>
  );
}

/** The followed player, pinned like a favourite: speed now, ground covered, top speed and what they did. */
export function ClipPinned({ stats, id, colours, events, info, onStop }: {
  stats: TrackStats | undefined; id: string; colours: [string, string]; events: ClipEventLine[]; info: ClipInfo | null; onStop: () => void;
}) {
  const side = id.startsWith("L-") ? 0 : 1;
  const colour = colours[side];
  const involved = events.filter(({ event }) => event.player_id === id || event.receiver_id === id).length;
  return (
    <div className="pinned" style={{ borderLeftColor: colour }}>
      <div className="pin-top">
        <span className="pin-number" style={{ background: colour }}>{id.split("-t")[1]}</span>
        <div className="pin-name">
          <b>{trackLabel(id)}</b>
          <small>★ Following · real tracked position{stats && !stats.seen ? " · lost by the tracker" : ""}</small>
        </div>
        {stats?.speed != null && stats.seen && <div className="pin-rating"><b className="bigrating">{Math.round(stats.speed * 3.6)}</b><small>km/h</small></div>}
        <button className="close" onClick={onStop} aria-label="Stop following" title="Stop following">×</button>
      </div>
      <div className="pin-stats">
        <span><em>Covered</em> <b>{stats ? Math.round(stats.distance) : 0} m</b></span>
        <span><em>Top speed</em> <b>{stats ? kmh(stats.topSpeed) : "–"}</b></span>
        <span><em>In events</em> <b>{involved}</b></span>
        {stats && <span><em>Detection</em> <b>{pct(stats.confidence)}</b></span>}
      </div>
      {info && <p className="empty">The tracker can swap IDs between players: on this clip a player keeps one ID for {pct(info.figures.id_consistency)} of frames.</p>}
    </div>
  );
}
