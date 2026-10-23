import type { CSSProperties } from "react";
import type { Cue, CueTemplate, MatchMeta, ViewMode } from "../types";

// Three regions, each a column that stacks its cues, so cues can't draw over each other whatever their
// height. The Director's rules (one of each template, at most two cards) keep the regions from filling up.
const REGIONS: { name: string; templates: CueTemplate[] }[] = [
  { name: "bottom", templates: ["player_tag", "lower_third"] },
  { name: "top-left", templates: ["rating_alert", "speed_popup"] },
  { name: "top-right", templates: ["stat_card"] },
];

const ROW_LABELS: Record<string, [string, string]> = {
  possession_pct: ["Possession", "%"], shots: ["Shots", ""], shots_on_target: ["On target", ""], xg: ["xG", ""],
  pass_accuracy_pct: ["Pass accuracy", "%"], field_tilt: ["Field tilt", "%"], pressures_high: ["High pressures", ""],
  ppda: ["PPDA", ""], tackles_won: ["Tackles won", ""], interceptions: ["Interceptions", ""],
};
const CARD_TITLES: Record<string, string> = { summary: "Match summary", control: "Who is in control", pressing: "Pressing" };
const TAG_EVENTS: Record<string, string> = { goal: "Goal", red_card: "Sent off" };

function teamColour(cue: Cue, meta: MatchMeta, colours: [string, string]): string | undefined {
  const t = cue.about.team_id;
  return t === meta.home.id ? colours[0] : t === meta.away.id ? colours[1] : undefined;
}

/** The overlays on the pitch for this viewer: what the Director sent, minus analyst-only cues for casual fans. */
export function Overlays({ cues, meta, mode, colours }: {
  cues: Cue[]; meta: MatchMeta; mode: ViewMode; colours: [string, string];
}) {
  const visible = cues.filter((c) => mode === "analyst" || c.detail === "casual");
  const draw = (cue: Cue) => {
    const accent = teamColour(cue, meta, colours);
    const style = accent ? ({ "--team": accent } as CSSProperties) : undefined;
    switch (cue.template) {
      case "lower_third": return <LowerThird key={cue.id} cue={cue} mode={mode} style={style} />;
      case "stat_card": return <StatCard key={cue.id} cue={cue} meta={meta} colours={colours} />;
      case "player_tag": return <PlayerTag key={cue.id} cue={cue} style={style} />;
      case "rating_alert": return <RatingAlert key={cue.id} cue={cue} style={style} />;
      case "speed_popup": return <SpeedPopup key={cue.id} cue={cue} style={style} />;
    }
  };
  return (
    <>
      {REGIONS.map((r) => (
        <div key={r.name} className={`cue-region ${r.name}`}>
          {r.templates.flatMap((t) => visible.filter((c) => c.template === t)).map(draw)}
        </div>
      ))}
    </>
  );
}

function LowerThird({ cue, mode, style }: { cue: Cue; mode: ViewMode; style?: CSSProperties }) {
  const d = cue.data;
  // The agents' line for this viewer; an analyst without one sees the next fact from the evidence pack.
  const text = (mode === "casual" ? d.casual : d.analyst) ?? (mode === "analyst" ? d.fact : null);
  return (
    <div className={`cue lowerthird ${cue.tier} kind-${d.kind}`} style={style} data-cue={cue.id}>
      <span className="lt-clock">{d.clock}</span>
      <span className="lt-head">{d.headline}</span>
      {text && <span className="lt-fact">{text}</span>}
    </div>
  );
}

function StatCard({ cue, meta, colours }: { cue: Cue; meta: MatchMeta; colours: [string, string] }) {
  const d = cue.data;
  return (
    <div className={`cue statcard ${d.kind}`} data-cue={cue.id}>
      <h4>{CARD_TITLES[d.kind] ?? "Match stats"} <small>{d.clock}</small></h4>
      <div className="sc-teams">
        <span><i style={{ background: colours[0] }} />{meta.home.short_name}</span>
        <span>{meta.away.short_name}<i style={{ background: colours[1] }} /></span>
      </div>
      {(d.rows as { key: string; home: number; away: number }[]).map((r) => {
        const [label, unit] = ROW_LABELS[r.key] ?? [r.key, ""];
        return (
          <div className="sc-row" key={r.key}>
            <b>{r.home}{unit}</b><span>{label}</span><b>{r.away}{unit}</b>
          </div>
        );
      })}
    </div>
  );
}

function PlayerTag({ cue, style }: { cue: Cue; style?: CSSProperties }) {
  const d = cue.data;
  return (
    <div className="cue playertag" style={style} data-cue={cue.id}>
      <span className="pt-number">{d.number ?? "–"}</span>
      <span className="pt-main">
        <b>{d.name}</b>
        <small>{TAG_EVENTS[d.event] ?? ""} {d.clock}{d.position ? ` · ${d.position}` : ""}</small>
      </span>
      {typeof d.rating === "number" && <span className="pt-rating">{d.rating.toFixed(1)}</span>}
    </div>
  );
}

function RatingAlert({ cue, style }: { cue: Cue; style?: CSSProperties }) {
  const d = cue.data;
  const arrow = d.direction === "down" ? "▼" : d.direction === "up" ? "▲" : "★";
  return (
    <div className={`cue ratingalert ${d.direction}`} style={style} data-cue={cue.id}>
      <span className="ra-arrow">{arrow}</span>
      <b>{d.name}</b>
      <span className="ra-rating">{typeof d.rating === "number" ? d.rating.toFixed(1) : ""}</span>
      {typeof d.change === "number" && <small>{d.change >= 0 ? "+" : ""}{d.change.toFixed(1)}</small>}
    </div>
  );
}

function SpeedPopup({ cue, style }: { cue: Cue; style?: CSSProperties }) {
  const d = cue.data;
  return (
    <div className="cue speedpopup" style={style} data-cue={cue.id}>
      <b>{d.speed_kmh}</b><small>km/h</small><span>{d.name}</span>
    </div>
  );
}
