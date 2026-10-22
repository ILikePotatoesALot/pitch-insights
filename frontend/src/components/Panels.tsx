import { useState } from "react";
import type { CommentaryInfo, LiveState, MatchMeta, Moment, PlayerState, ViewMode } from "../types";

const pct = (p: number) => `${Math.round(p * 100)}%`;

export function Scoreboard({ meta, state, colours }: { meta: MatchMeta; state: LiveState | null; colours: [string, string] }) {
  const h = meta.home.id, a = meta.away.id;
  const score = state?.score ?? { [h]: 0, [a]: 0 };
  const wp = state?.win_probability ?? { home: 0.45, draw: 0.27, away: 0.28 };
  return (
    <div className="scoreboard">
      <div className="teams">
        <span className="team"><i style={{ background: colours[0] }} />{meta.home.name}</span>
        <span className="score">{score[h]}<em>–</em>{score[a]}</span>
        <span className="team away">{meta.away.name}<i style={{ background: colours[1] }} /></span>
      </div>
      <div className="clock">{state?.finished ? "Full time" : state?.clock ?? "0'"}</div>
      <div className="winprob" title="Live win probability">
        <div style={{ width: pct(wp.home), background: colours[0] }}>{wp.home >= 0.12 && pct(wp.home)}</div>
        <div className="draw" style={{ width: pct(wp.draw) }}>{wp.draw >= 0.12 && `Draw ${pct(wp.draw)}`}</div>
        <div style={{ width: pct(wp.away), background: colours[1] }}>{wp.away >= 0.12 && pct(wp.away)}</div>
      </div>
    </div>
  );
}

export function MomentumChart({ state, colours }: { state: LiveState | null; colours: [string, string] }) {
  const series = state?.momentum_series ?? [];
  const n = Math.max(series.length, 95);
  const w = 600, h = 64, mid = h / 2;
  const x = (i: number) => (i / (n - 1)) * w;
  const ht = series.findIndex((s) => s.period === 2);
  const above = series.map((s, i) => `${x(i)},${mid - (Math.max(0, s.value) / 100) * mid}`).join(" ");
  const below = series.map((s, i) => `${x(i)},${mid - (Math.min(0, s.value) / 100) * mid}`).join(" ");
  const last = series.length ? x(series.length - 1) : 0;
  return (
    <div className="panel">
      <h3>Momentum <small>who is creating the threat (last 5 minutes)</small></h3>
      <svg viewBox={`0 0 ${w} ${h}`} className="momentum" preserveAspectRatio="none">
        <line x1="0" x2={w} y1={mid} y2={mid} className="axis" />
        {ht > 0 && <line x1={x(ht)} x2={x(ht)} y1="0" y2={h} className="axis dashed" />}
        {series.length > 1 && <>
          <polygon points={`0,${mid} ${above} ${last},${mid}`} fill={colours[0]} opacity="0.85" />
          <polygon points={`0,${mid} ${below} ${last},${mid}`} fill={colours[1]} opacity="0.85" />
        </>}
      </svg>
    </div>
  );
}

/** The agents' line for this viewer, if they wrote one (a fallback is just the headline again). */
export function commentaryText(m: Moment, mode: ViewMode): string | null {
  const c = m.commentary;
  if (!c || c.status !== "ok") return null;
  return mode === "casual" ? c.casual : c.analyst;
}

function CheckNote({ m }: { m: Moment }) {
  const c = m.commentary;
  if (!c) return null;
  if (c.status !== "ok") return <p className="check">AI commentary unavailable ({c.reason}); showing the plain headline.</p>;
  const g = c.grounding;
  return (
    <p className="check">
      {c.agent === "explainer" ? "Explainer" : "Narrator"} agent · {g ? `${g.claims} names and numbers checked against these facts` : "checked"}
      {c.corrected.length > 0 && `; first draft corrected (${c.corrected.join(", ")} weren't in the facts)`}
      {c.safety?.passed && " · screened by Azure AI Content Safety"}
      {m.lang && " · machine-translated by Azure AI Translator"}
    </p>
  );
}

function MomentCard({ m, meta, mode, colours }: { m: Moment; meta: MatchMeta; mode: ViewMode; colours: [string, string] }) {
  const [open, setOpen] = useState(false);
  const colour = m.team_id === meta.home.id ? colours[0] : m.team_id === meta.away.id ? colours[1] : "var(--muted)";
  const text = commentaryText(m, mode);
  return (
    <li className={`moment ${m.tier}`} style={{ borderLeftColor: colour }}>
      <button onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="mclock">{m.clock}</span>
        <span className="mhead">{m.headline}{text && <span className="mtext">{text}</span>}</span>
        <span className="why">{open ? "Hide" : "Why?"}</span>
      </button>
      {open && <>
        <ul className="facts">{m.facts.map((f, i) => <li key={i}>{f.text}</li>)}</ul>
        <CheckNote m={m} />
      </>}
    </li>
  );
}

export function MomentFeed({ moments, meta, aiInfo, mode, colours }: {
  moments: Moment[]; meta: MatchMeta; aiInfo: CommentaryInfo | null; mode: ViewMode; colours: [string, string];
}) {
  const [showMinor, setShowMinor] = useState(false);
  const shown = moments.filter((m) =>
    mode === "casual" ? m.tier === "headline" : m.tier !== "minor" || showMinor);
  return (
    <div className="panel feed">
      <h3>
        Key moments <small>{mode === "casual" ? "the big ones" : "with the evidence behind them"}</small>
        {mode === "analyst" && <label className="toggle"><input type="checkbox" checked={showMinor} onChange={(e) => setShowMinor(e.target.checked)} /> minor</label>}
      </h3>
      {shown.length === 0 ? <p className="empty">Nothing yet. Moments appear here as the match unfolds.</p> :
        <ul>{[...shown].reverse().map((m) => <MomentCard key={m.id} m={m} meta={meta} mode={mode} colours={colours} />)}</ul>}
      {aiInfo && <p className="ai-note">Commentary is AI-generated ({aiInfo.model}) from the facts under "Why?", and every name and number in it is checked against them.
        {moments.some((m) => m.lang) && " Moments are machine-translated from English."}</p>}
    </div>
  );
}

function PlayerCard({ p, onClose }: { p: PlayerState; onClose: () => void }) {
  const cats = Object.entries(p.by_category);
  const max = Math.max(0.5, ...cats.map(([, v]) => Math.abs(v)));
  return (
    <div className="playercard">
      <div className="pc-top">
        <div><b>{p.name}</b> <small>#{p.number} · {p.position} · {Math.round(p.minutes)}'</small></div>
        <span className="bigrating">{p.rating.toFixed(1)}</span>
        <button className="close" onClick={onClose} aria-label="Close">×</button>
      </div>
      <div className="pc-stats">
        <span>Goals <b>{p.goals}</b></span><span>Assists <b>{p.assists}</b></span>
        <span>Shots <b>{p.shots}</b></span><span>xG <b>{p.xg.toFixed(2)}</b></span>
        <span>Passes <b>{p.passes_complete}/{p.passes}</b></span><span>Key passes <b>{p.key_passes}</b></span>
        <span>Tackles won <b>{p.tackles_won}</b></span><span>Interceptions <b>{p.interceptions}</b></span>
      </div>
      <h4>Why {p.rating.toFixed(1)}?</h4>
      {cats.map(([k, v]) => (
        <div className="bar" key={k}>
          <span>{k}</span>
          <div><i className={v >= 0 ? "pos" : "neg"} style={{ width: `${(Math.abs(v) / max) * 100}%` }} /></div>
          <b>{v >= 0 ? "+" : ""}{v.toFixed(2)}</b>
        </div>
      ))}
      {p.key_moments.length > 0 && <ul className="kms">{p.key_moments.map((k, i) => (
        <li key={i}><span>{k.clock}</span> {k.label} <b>{k.delta >= 0 ? "+" : ""}{k.delta.toFixed(2)}</b></li>))}</ul>}
    </div>
  );
}

export function Ratings({ state, meta, colours, favourite, setFavourite }: {
  state: LiveState | null; meta: MatchMeta; colours: [string, string];
  favourite: string | null; setFavourite: (id: string | null) => void;
}) {
  const players = state?.players ?? [];
  const fav = players.find((p) => p.player_id === favourite);
  const teamCol = (t: string) => (t === meta.home.id ? colours[0] : colours[1]);
  const top = [...players].filter((p) => p.minutes >= 1).sort((a, b) => b.rating - a.rating).slice(0, 8);
  return (
    <div className="panel ratings">
      <h3>Live ratings <small>tap a player</small></h3>
      {fav && <PlayerCard p={fav} onClose={() => setFavourite(null)} />}
      <ol>
        {top.map((p) => (
          <li key={p.player_id} onClick={() => setFavourite(p.player_id)} className={p.player_id === favourite ? "active" : ""}>
            <i style={{ background: teamCol(p.team_id) }} />
            <span className="pname">{p.name}</span>
            <small>{p.position}{!p.on_pitch && " · off"}</small>
            <b className={p.rating >= 7.5 ? "hi" : p.rating < 6 ? "lo" : ""}>{p.rating.toFixed(1)}</b>
          </li>
        ))}
      </ol>
    </div>
  );
}

const ROWS: [string, (t: LiveState["teams"][string]) => string | number][] = [
  ["Possession", (t) => `${t.possession_pct}%`],
  ["Shots (on target)", (t) => `${t.shots} (${t.shots_on_target})`],
  ["xG", (t) => t.xg.toFixed(2)],
  ["Big chances", (t) => t.big_chances],
  ["Pass accuracy", (t) => `${t.pass_accuracy_pct}%`],
  ["Progressive passes", (t) => t.progressive_passes],
  ["Threat added (xT)", (t) => t.xt_added.toFixed(2)],
  ["High pressures", (t) => t.pressures_high],
  ["PPDA", (t) => t.ppda ?? "–"],
  ["Corners", (t) => t.corners],
  ["Fouls", (t) => t.fouls],
  ["Cards", (t) => `${t.yellows}Y ${t.reds}R`],
];

export function StatsPanel({ state, meta }: { state: LiveState | null; meta: MatchMeta }) {
  if (!state) return null;
  const h = state.teams[meta.home.id], a = state.teams[meta.away.id];
  const p = state.patterns;
  return (
    <div className="panel stats">
      <h3>Match stats</h3>
      <table>
        <thead><tr><th>{meta.home.short_name}</th><th /><th>{meta.away.short_name}</th></tr></thead>
        <tbody>{ROWS.map(([label, f]) => <tr key={label}><td>{f(h)}</td><th>{label}</th><td>{f(a)}</td></tr>)}</tbody>
      </table>
      <p className="patterns">
        Last 5 min: tempo <b>{p.tempo}</b> passes/min · chaos <b>{p.chaos.toFixed(2)}</b> · high pressures/min{" "}
        <b>{p.pressure[meta.home.id]}</b> vs <b>{p.pressure[meta.away.id]}</b>
      </p>
    </div>
  );
}
