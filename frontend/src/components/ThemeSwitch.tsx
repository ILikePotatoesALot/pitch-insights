import { setTheme, useTheme, type Theme } from "../theme";

export function ThemeSwitch() {
  const theme = useTheme();
  return (
    <div className="theme-control">
      <span className="setting-label">Appearance</span>
      <div className="segmented" role="group" aria-label="Appearance">
        {(["light", "dark"] as Theme[]).map((value) => (
          <button type="button" key={value} className={theme === value ? "on" : ""} aria-pressed={theme === value}
                  onClick={() => setTheme(value)}>{value === "light" ? "Light" : "Dark"}</button>
        ))}
      </div>
    </div>
  );
}
