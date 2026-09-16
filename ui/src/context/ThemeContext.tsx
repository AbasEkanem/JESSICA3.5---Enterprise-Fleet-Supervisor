"use client";

import { createContext, useContext, useEffect, useState, useCallback, ReactNode } from "react";

type Theme = "dark" | "light";
/** User's chosen preference. "auto" resolves to dark/light by local time of day. */
type ThemePreference = "dark" | "light" | "auto";

interface ThemeContextValue {
  /** The resolved, currently-applied theme. */
  theme: Theme;
  /** The user's stored preference ("auto" | "dark" | "light"). */
  preference: ThemePreference;
  /** Cycle dark → light → auto → dark. */
  toggle: () => void;
  /** Explicitly set a preference. */
  setPreference: (p: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: "dark",
  preference: "auto",
  toggle: () => {},
  setPreference: () => {},
});

/**
 * Resolve the time-of-day theme.
 * Daytime  (07:00–18:59) → light  ("amazing daytime")
 * Nighttime (19:00–06:59) → dark  ("calm night sky")
 */
function timeOfDayTheme(now: Date = new Date()): Theme {
  const h = now.getHours();
  return h >= 7 && h < 19 ? "light" : "dark";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>("auto");
  const [theme, setTheme] = useState<Theme>("dark");

  // Load stored preference once on mount.
  useEffect(() => {
    const stored = localStorage.getItem("jessica-theme-pref") as ThemePreference | null;
    // Back-compat: older builds stored a resolved theme under "jessica-theme".
    const legacy = localStorage.getItem("jessica-theme") as Theme | null;
    if (stored === "dark" || stored === "light" || stored === "auto") {
      setPreferenceState(stored);
    } else if (legacy === "dark" || legacy === "light") {
      setPreferenceState(legacy);
    }
  }, []);

  // Resolve the applied theme whenever the preference changes,
  // and — when in auto mode — re-check on a timer so it flips at dawn/dusk.
  useEffect(() => {
    const resolve = () => {
      setTheme(preference === "auto" ? timeOfDayTheme() : preference);
    };
    resolve();

    if (preference === "auto") {
      const id = setInterval(resolve, 60_000); // re-check every minute
      return () => clearInterval(id);
    }
  }, [preference]);

  // Apply the resolved theme to the DOM + persist the preference.
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.setAttribute("data-theme-pref", preference);
    localStorage.setItem("jessica-theme-pref", preference);
    // Keep legacy key in sync so any other reader still works.
    localStorage.setItem("jessica-theme", theme);
  }, [theme, preference]);

  const setPreference = useCallback((p: ThemePreference) => setPreferenceState(p), []);

  // Cycle: if in auto mode, switch to opposite of current active theme; otherwise cycle dark ↔ light ↔ auto
  const toggle = useCallback(() => {
    setPreferenceState(prev => {
      if (prev === "auto") {
        const active = timeOfDayTheme();
        return active === "dark" ? "light" : "dark";
      }
      if (prev === "dark") return "light";
      if (prev === "light") return "auto";
      return "dark";
    });
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, preference, toggle, setPreference }}>
      {children}
    </ThemeContext.Provider>
  );
}

export const useTheme = () => useContext(ThemeContext);
