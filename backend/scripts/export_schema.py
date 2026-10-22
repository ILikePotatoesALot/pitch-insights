"""Write the JSON Schema for the event format to docs/schema/ (input for frontend TypeScript types)."""

import json
from pathlib import Path

from pitch_insights.events.schema import Frame, MatchMeta, event_adapter

out = Path(__file__).resolve().parents[2] / "docs" / "schema"
out.mkdir(parents=True, exist_ok=True)
(out / "event.schema.json").write_text(json.dumps(event_adapter.json_schema(by_alias=True), indent=2))
(out / "match_meta.schema.json").write_text(json.dumps(MatchMeta.model_json_schema(by_alias=True), indent=2))
(out / "frame.schema.json").write_text(json.dumps(Frame.model_json_schema(by_alias=True), indent=2))
print(f"Wrote schemas to {out}")
