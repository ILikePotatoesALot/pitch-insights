import type { ClipEventLine, ClipInfo, MatchMeta, ViewMode } from "../types";
import { trackLabel } from "../pitch/ClipLayer";

const pct = (v: number) => `${Math.round(v * 100)}%`;

/** Time into the half as the match clock shows it: 2280 s is 38:00. */
export const mmss = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t) % 60).padStart(2, "0")}`;

/** In place of the scoreboard: who is playing, that this is real footage, and how far into the clip the replay is. */
export function ClipBanner({ meta, info, t, colours }: { meta: MatchMeta; info: ClipInfo | null; t: number | null; colours: [string, string] }) {
  const start = info?.clip.start ?? 0, length = info?.clip.duration ?? 1;
  const at = t === null ? start : t;
  return (
    <div className="scoreboard clip-banner">
      <div className="teams">
        <span className="team"><i style={{ background: colours[0] }} />{meta.home.name}</span>
        <span className="clip-tag" title="Positions measured from match video by a computer-vision model">Real footage</span>
        <span className="team away">{meta.away.name}<i style={{ background: colours[1] }} /></span>
      </div>
      <div className="clock">{mmss(at)} <small>first half · clip {info ? `${info.clip.from} to ${info.clip.to}` : ""}</small></div>
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

/** The credibility panel: the benchmark figures, the model, the credit and what the figures do not cover. */
export function ClipPanel({ info, lang }: { info: ClipInfo; lang: string }) {
  const f = info.figures;
  const rows: [string, string, string][] = [
    ["Precision", pct(f.precision), "tracked people that are real players"],
    ["Recall", pct(f.recall), "players found, within " + f.match_radius_m + " m"],
    ["Position error", `${f.position_error_mean_m.toFixed(2)} m`, `mean; median ${f.position_error_median_m.toFixed(2)} m, 90% within ${f.position_error_p90_m.toFixed(1)} m`],
    ["Team accuracy", pct(f.team_accuracy), "side read from shirt colour"],
  ];
  return (
    <div className="panel clip-panel">
      <h3>Where these positions come from</h3>
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
    </div>
  );
}

/** The events the video path detected so far, newest first, with how sure it was. */
export function ClipEvents({ events, mode, colours, meta, info }: {
  events: ClipEventLine[]; mode: ViewMode; colours: [string, string]; meta: MatchMeta; info: ClipInfo | null;
}) {
  return (
    <div className="panel feed">
      <h3>Detected events <small>{mode === "casual" ? "passes, carries and interceptions" : "inferred from the ball and who was nearest"}</small></h3>
      {events.length === 0 ? <p className="empty">Nothing yet. Events appear here as the clip plays.</p> : (
        <ul>
          {[...events].reverse().map(({ event, text }) => {
            const colour = event.team_id === meta.home.id ? colours[0] : event.team_id === meta.away.id ? colours[1] : "var(--muted)";
            return (
              <li className="moment" key={event.seq} style={{ borderLeftColor: colour }} title={event.player_id ? trackLabel(event.player_id) : undefined}>
                <div className="clip-event">
                  <span className="mclock">{mmss(event.t)}</span>
                  <span className="mhead">{text}</span>
                  {mode === "analyst" && <span className="why">{pct(event.confidence)} sure</span>}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <p className="ai-note">No AI commentary here: these are the video path's own detections.
        {info && ` Within five seconds of SoccerTrack's labels, ${pct(info.figures.event_precision)} of what it reports is real and it finds ${pct(info.figures.event_recall)} of the real events.`}</p>
    </div>
  );
}
