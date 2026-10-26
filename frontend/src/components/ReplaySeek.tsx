import { useEffect, useId, useState } from "react";

export function ReplaySeek({ value, max, unit, positionLabel, onChange, onSeek, inputLabel }: {
  value: number; max: number; unit: "minute" | "second"; positionLabel: string;
  onChange: (value: number) => void; onSeek: (value: number) => void;
  inputLabel?: string;
}) {
  const id = useId();
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value, max]);
  const valid = (text: string) => text.trim() !== "" && Number.isInteger(Number(text)) && Number(text) >= 0 && Number(text) <= max;

  return (
    <form className="seek" onSubmit={(event) => {
      event.preventDefault();
      if (valid(draft)) onSeek(Number(draft));
    }}>
      <label htmlFor={`${id}-range`}>Jump to</label>
      <input id={`${id}-range`} type="range" min={0} max={max} step={1} value={value}
             aria-label="Replay position" aria-valuetext={positionLabel} onChange={(event) => onChange(Number(event.target.value))} />
      <span className="seek-value">
        <input type="number" required min={0} max={max} step={1} value={draft} inputMode="numeric"
               aria-label={inputLabel ?? (unit === "minute" ? "Match minute" : "Seconds into clip")} onChange={(event) => {
                 setDraft(event.target.value);
                 if (valid(event.target.value)) onChange(Number(event.target.value));
               }} />
        <span>{unit === "minute" ? "min" : "s"}</span>
      </span>
      <button type="submit">Go</button>
    </form>
  );
}
