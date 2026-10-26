import { useState } from "react";
import { focusLabel } from "../profile";
import type { CommentaryInfo, FocusMetric, LiveState, MatchMeta, Moment, PlayerState, ViewMode } from "../types";

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
      <div className="winprob-label">Win probability</div>
      <div className="winprob" role="img" aria-label={`Win probability: ${meta.home.name} ${pct(wp.home)}, draw ${pct(wp.draw)}, ${meta.away.name} ${pct(wp.away)}`}>
        <div style={{ width: pct(wp.home), background: colours[0] }}>{wp.home >= 0.12 && pct(wp.home)}</div>
        <div className="draw" style={{ width: pct(wp.draw) }}>{wp.draw >= 0.12 && `Draw ${pct(wp.draw)}`}</div>
        <div style={{ width: pct(wp.away), background: colours[1] }}>{wp.away >= 0.12 && pct(wp.away)}</div>
      </div>
      <div className="winprob-key" aria-hidden="true"><span>{meta.home.short_name}</span><span>Draw</span><span>{meta.away.short_name}</span></div>
    </div>
  );
}

type TeamNumbers = Record<string, number | null | undefined>;

/** A team's value for a focus metric, as text ("1.23", "55%"). */
function teamFocusValue(state: LiveState, side: "home" | "away", teamId: string, focus: FocusMetric): string {
  if (focus === "win_probability") return pct(state.win_probability[side]);
  const v = (state.teams[teamId] as unknown as TeamNumbers)[focus];
  if (v === null || v === undefined) return "–";
  return focus === "xg" || focus === "xt_added" ? v.toFixed(2) : focus.endsWith("_pct") ? `${v}%` : String(v);
}

/** The viewer's focus metric, for both teams: shown whatever the layout or mode. */
export function FocusStrip({ meta, state, colours, focus }: {
  meta: MatchMeta; state: LiveState | null; colours: [string, string]; focus: FocusMetric | null;
}) {
  if (!focus) return null;
  const sides: ["home" | "away", string, string][] = [["home", meta.home.id, colours[0]], ["away", meta.away.id, colours[1]]];
  return (
    <div className="focus-strip" title="Your focus metric (change it under Profile)">
      <span className="fs-label">★ {focusLabel(focus)}</span>
      {sides.map(([side, id, colour]) => (
        <span className="fs-val" key={side}><i style={{ background: colour }} />{meta[side].short_name} <b>{state ? teamFocusValue(state, side, id, focus) : "–"}</b></span>
      ))}
    </div>
  );
}

/** The favourite's value for the focus metric, when the metric makes sense for one player. */
function playerFocus(p: PlayerState, focus: FocusMetric | null): [string, string] | null {
  switch (focus) {
    case "xt_added": return ["xT added", p.xt_added.toFixed(2)];
    case "xg": return ["xG", p.xg.toFixed(2)];
    case "shots": return ["Shots", String(p.shots)];
    case "pass_accuracy_pct": return ["Pass accuracy", p.passes ? `${Math.round((100 * p.passes_complete) / p.passes)}%` : "–"];
    default: return null;
  }
}

function Sparkline({ values, colour }: { values: number[]; colour: string }) {
  if (values.length < 2) return <svg className="spark" viewBox="0 0 100 24" aria-hidden />;
  const lo = Math.min(...values, 6) - 0.2, hi = Math.max(...values, 7) + 0.2;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 100},${24 - ((v - lo) / (hi - lo)) * 24}`).join(" ");
  return (
    <svg className="spark" viewBox="0 0 100 24" preserveAspectRatio="none" role="img" aria-label="Rating through the match">
      <polyline points={pts} fill="none" stroke={colour} strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/** The viewer's favourite player, pinned: live rating with its trend, and the stats that suit their mode. */
export function PinnedPlayer({ state, meta, colours, playerId, mode, focus, history, onChange }: {
  state: LiveState | null; meta: MatchMeta; colours: [string, string]; playerId: string; mode: ViewMode;
  focus: FocusMetric | null; history: number[]; onChange: () => void;
}) {
  const home = meta.home.players.find((p) => p.id === playerId);
  const person = home ?? meta.away.players.find((p) => p.id === playerId);
  if (!person) return null;
  const colour = home ? colours[0] : colours[1];
  const p = state?.players.find((x) => x.player_id === playerId);
  const here = p ? playerFocus(p, focus) : null;
  const stats: [string, string][] = p ? [
    ["Goals", String(p.goals)], ["Assists", String(p.assists)], ["Shots", String(p.shots)],
    ["Passes", `${p.passes_complete}/${p.passes}`],
    ...(mode === "analyst" ? [["xG", p.xg.toFixed(2)], ["xT added", p.xt_added.toFixed(2)], ["Key passes", String(p.key_passes)],
      ["Tackles won", String(p.tackles_won)]] as [string, string][] : []),
  ] : [];
  const before = history.length > 1 ? history[Math.max(0, history.length - 11)] : null;
  const delta = p && before !== null ? p.rating - before : null;
  return (
    <div className="pinned" style={{ borderLeftColor: colour }}>
      <div className="pin-top">
        <span className="pin-number" style={{ background: colour }}>{person.number}</span>
        <div className="pin-name">
          <b>{person.name}</b>
          <small>★ Your player · {person.position}{p && !p.on_pitch ? " · off" : ""}</small>
          <small>{meta.tracking ? "Ring: continuous simulated position" : "Ring: last recorded action position"}</small>
        </div>
        {p && <div className="pin-rating">
          <b className="bigrating">{p.rating.toFixed(1)}</b>
          {delta !== null && Math.abs(delta) >= 0.05 && <small className={delta > 0 ? "up" : "down"}>{delta > 0 ? "▲" : "▼"} {Math.abs(delta).toFixed(1)}</small>}
        </div>}
        <button className="close" onClick={onChange} aria-label="Change your player" title="Change your player">⋯</button>
      </div>
      {p ? <>
        <Sparkline values={history} colour={colour} />
        <div className="pin-stats">
          {here && <span className="focus"><em>{here[0]}</em> <b>{here[1]}</b></span>}
          {stats.filter(([k]) => k !== here?.[0]).map(([k, v]) => <span key={k}><em>{k}</em> <b>{v}</b></span>)}
        </div>
      </> : <p className="empty">Waiting for the match to start…</p>}
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
      {{ explainer: "Explainer", narrator: "Narrator", video_narrator: "Video narrator" }[c.agent]} agent · {g ? `${g.claims} names and numbers checked against these facts` : "checked"}
      {c.corrected.length > 0 && `; first draft corrected (${c.corrected.join(", ")} weren't in the facts)`}
      {c.safety?.passed && " · screened by Azure AI Content Safety"}
      {m.lang && " · machine-translated by Azure AI Translator"}
    </p>
  );
}

function MomentCard({ m, meta, mode, colours, mine }: {
  m: Moment; meta: MatchMeta; mode: ViewMode; colours: [string, string]; mine: boolean;
}) {
  const [open, setOpen] = useState(false);
  const colour = m.team_id === meta.home.id ? colours[0] : m.team_id === meta.away.id ? colours[1] : "var(--muted)";
  const text = commentaryText(m, mode);
  return (
    <li className={`moment ${m.tier}${mine ? " mine" : ""}`} style={{ borderLeftColor: colour }}>
      <button onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="mclock">{m.clock}</span>
        <span className="mhead">{mine && "★ "}{m.headline}{text && <span className="mtext">{text}</span>}</span>
        <span className="why">{open ? "Hide" : "Why?"}</span>
      </button>
      {open && <>
        <ul className="facts">{m.facts.map((f, i) => <li key={i}>{f.text}</li>)}</ul>
        <CheckNote m={m} />
      </>}
    </li>
  );
}

/**
 * The moments so far, newest first. A casual fan sees only headline moments, unless `allTiers` (a clip, whose few
 * moments are all worth showing). `follow` is a player whose moments get a star (a tracked player in a clip).
 */
export function MomentFeed({ moments, meta, aiInfo, mode, colours, allTiers = false, follow = null }: {
  moments: Moment[]; meta: MatchMeta; aiInfo: CommentaryInfo | null; mode: ViewMode; colours: [string, string];
  allTiers?: boolean; follow?: string | null;
}) {
  const [showMinor, setShowMinor] = useState(false);
  const shown = moments.filter((m) =>
    mode === "casual" && !allTiers ? m.tier === "headline" : m.tier !== "minor" || showMinor);
  return (
    <div className="panel feed">
      <h3>
        Key moments <small>{mode === "casual" ? "the big ones" : "with the evidence behind them"}</small>
        {mode === "analyst" && <label className="toggle"><input type="checkbox" checked={showMinor} onChange={(e) => setShowMinor(e.target.checked)} /> minor</label>}
      </h3>
      {shown.length === 0 ? <p className="empty">Nothing yet. Moments appear here as the match unfolds.</p> :
        <ul>{[...shown].reverse().map((m) => <MomentCard key={m.id} m={m} meta={meta} mode={mode} colours={colours}
                                                         mine={!!follow && m.player_id === follow} />)}</ul>}
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

export function Ratings({ state, meta, colours, favourite, setFavourite, followed, onFollow }: {
  state: LiveState | null; meta: MatchMeta; colours: [string, string];
  favourite: string | null; setFavourite: (id: string | null) => void;
  followed: string | null; onFollow: (id: string) => void;
}) {
  const players = state?.players ?? [];
  const fav = players.find((p) => p.player_id === favourite);
  const teamCol = (t: string) => (t === meta.home.id ? colours[0] : colours[1]);
  const top = [...players].sort((a, b) => b.rating - a.rating).slice(0, 8);
  return (
    <div className="panel ratings">
      <h3>Live ratings <small>tap a player to follow</small></h3>
      {fav && <PlayerCard p={fav} onClose={() => setFavourite(null)} />}
      <ol>
        {top.map((p) => (
          <li key={p.player_id} className={p.player_id === followed ? "active" : ""}>
            <button type="button" className="player-row" aria-label={`Follow ${p.name}`} aria-pressed={p.player_id === followed}
                    onClick={() => { setFavourite(p.player_id); onFollow(p.player_id); }}>
            <i style={{ background: teamCol(p.team_id) }} />
            <span className="pname">{p.player_id === followed && "★ "}{p.name}</span>
            <small>{p.position}{!p.on_pitch && " · off"}</small>
            <b className={p.rating >= 7.5 ? "hi" : p.rating < 6 ? "lo" : ""}>{p.rating.toFixed(1)}</b>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}

// The key of a row is the focus metric it answers to (a row without one can't be a focus).
const ROWS: [string, string, (t: LiveState["teams"][string]) => string | number][] = [
  ["possession_pct", "Possession", (t) => `${t.possession_pct}%`],
  ["shots", "Shots (on target)", (t) => `${t.shots} (${t.shots_on_target})`],
  ["xg", "xG", (t) => t.xg.toFixed(2)],
  ["", "Big chances", (t) => t.big_chances],
  ["pass_accuracy_pct", "Pass accuracy", (t) => `${t.pass_accuracy_pct}%`],
  ["", "Progressive passes", (t) => t.progressive_passes],
  ["xt_added", "Threat added (xT)", (t) => t.xt_added.toFixed(2)],
  ["", "High pressures", (t) => t.pressures_high],
  ["", "PPDA", (t) => t.ppda ?? "–"],
  ["", "Corners", (t) => t.corners],
  ["", "Fouls", (t) => t.fouls],
  ["", "Cards", (t) => `${t.yellows}Y ${t.reds}R`],
];

export function StatsPanel({ state, meta, focus }: { state: LiveState | null; meta: MatchMeta; focus: FocusMetric | null }) {
  if (!state) return null;
  const h = state.teams[meta.home.id], a = state.teams[meta.away.id];
  const p = state.patterns;
  return (
    <div className="panel stats">
      <h3>Match stats</h3>
      <table>
        <thead><tr><th>{meta.home.short_name}</th><th /><th>{meta.away.short_name}</th></tr></thead>
        <tbody>
          {focus === "win_probability" && <tr className="focus"><td>{pct(state.win_probability.home)}</td><th>★ Win probability</th><td>{pct(state.win_probability.away)}</td></tr>}
          {ROWS.map(([key, label, f]) => <tr key={label} className={key && key === focus ? "focus" : ""}><td>{f(h)}</td><th>{key && key === focus ? "★ " : ""}{label}</th><td>{f(a)}</td></tr>)}
        </tbody>
      </table>
      <p className="patterns">
        Last 5 min: tempo <b>{p.tempo}</b> passes/min · chaos <b>{p.chaos.toFixed(2)}</b> · high pressures/min{" "}
        <b>{p.pressure[meta.home.id]}</b> vs <b>{p.pressure[meta.away.id]}</b>
      </p>
    </div>
  );
}
