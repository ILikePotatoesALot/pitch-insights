import type { MatchMeta, PositionAnalysis } from "../types";

export function PositionInsights({ meta, position }: { meta: MatchMeta; position: PositionAnalysis | null }) {
  if (!position) return null;
  return <div className="panel position-insights">
    <h3>Position insights <small>measured from player positions</small></h3>
    <table><thead><tr><th>{meta.home.short_name}</th><th /><th>{meta.away.short_name}</th></tr></thead>
      <tbody>{([['width', 'Team width'], ['depth', 'Team depth'], ['defensive_line', 'Defensive line'], ['near_ball', 'Within 5 m of ball']] as const).map(([key, label]) =>
        <tr key={key}><td>{position.teams[meta.home.id]?.[key]}{key !== 'near_ball' && ' m'}</td><th>{label}</th>
          <td>{position.teams[meta.away.id]?.[key]}{key !== 'near_ball' && ' m'}</td></tr>)}</tbody></table>
    <p className="exhibition-note">Outfield players only. Defensive line is the defenders’ median distance from their own goal line. Proximity does not establish a successful press.</p>
  </div>;
}
