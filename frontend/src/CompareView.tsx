import { useMemo } from "react";
import { ThemeSwitch } from "./components/ThemeSwitch";

// Two viewers of one match, side by side: each pane is the whole app in an iframe, with its own profile in its
// own link (so neither saves anything, and the two never overwrite each other). Both connect at once and the
// server plays each from kick-off on its own clock, so the same match unfolds in both. Meant for the demo's hero shot.
//
//   /?compare=1                         the two default viewers
//   /?compare=1&match=thriller-CAR-BRO&speed=5&a=<query for the left pane>&b=<query for the right pane>
//
// A pane's query is any profile link: team=, player=, mode=, lang=, focus=, layout=.
const PRESETS = {
  a: "team=POT&player=POT-11&mode=casual&lang=de&focus=win_probability&layout=broadcast",
  b: "team=CAR&player=CAR-10&mode=analyst&lang=en&focus=xt_added&layout=broadcast",
};

export default function CompareView() {
  const panes = useMemo(() => {
    const q = new URLSearchParams(location.search);
    const shared = new URLSearchParams();
    for (const k of ["match", "speed"]) if (q.get(k)) shared.set(k, q.get(k)!);
    return (["a", "b"] as const).map((side) => {
      const own = new URLSearchParams(q.get(side) ?? PRESETS[side]);
      own.set("embed", "1");
      for (const [k, v] of shared) own.set(k, v);
      return `/?${own}`;
    });
  }, []);
  const single = new URLSearchParams(panes[0].slice(2));
  single.delete("embed");
  return (
    <div className="compare-page">
      <div className="compare-toolbar"><a href={`/?${single}`}>Watch one match</a><ThemeSwitch /></div>
      <p className="compare-mobile-note">Two viewers is best on a larger screen. You can watch one match with all the same controls.</p>
      <div className="compare-view">
        {panes.map((src, i) => <iframe key={i} src={src} title={i === 0 ? "Viewer A" : "Viewer B"} />)}
      </div>
    </div>
  );
}
