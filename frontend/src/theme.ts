import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";
const KEY = "pitch-insights.theme.v1";
const CHANGED = "pitch-insights-theme-change";

function storedTheme(): Theme {
  try { return window.localStorage.getItem(KEY) === "dark" ? "dark" : "light"; }
  catch { return "light"; }
}

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
}

/** Light is the first-visit default, including when the device prefers dark or storage is blocked. */
export function initialiseTheme() { applyTheme(storedTheme()); }

export function themeSnapshot(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

export function setTheme(theme: Theme) {
  applyTheme(theme);
  try { window.localStorage.setItem(KEY, theme); } catch { /* keep the choice for this visit */ }
  window.dispatchEvent(new Event(CHANGED));
}

/** Storage events reach other tabs and comparison panes; the custom event reaches this document. */
export function subscribeTheme(changed: () => void) {
  const storage = (event: StorageEvent) => {
    if (event.key !== KEY && event.key !== null) return;
    applyTheme(storedTheme());
    changed();
  };
  window.addEventListener("storage", storage);
  window.addEventListener(CHANGED, changed);
  return () => {
    window.removeEventListener("storage", storage);
    window.removeEventListener(CHANGED, changed);
  };
}

export function useTheme() { return useSyncExternalStore(subscribeTheme, themeSnapshot); }
