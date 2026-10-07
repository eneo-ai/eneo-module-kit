import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type ColorMode = "light" | "dark" | "system";

/** The key and values next-themes used, so a person's choice made in an app on it carries over (design K9). */
export const COLOR_MODE_KEY = "theme";

const MODES: readonly string[] = ["light", "dark", "system"];
const DARK = "(prefers-color-scheme: dark)";

function browserStorage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    // Reading the property itself can throw (blocked site data).
    return null;
  }
}

/**
 * The stored choice, read at once, before anything renders: light, dark or system. Anything else, or storage that is
 * missing or throws, is no choice, and no choice is system.
 */
export function readStoredColorMode(storage: Pick<Storage, "getItem"> | null = browserStorage()): ColorMode {
  try {
    const stored = storage?.getItem(COLOR_MODE_KEY);
    return stored && MODES.includes(stored) ? (stored as ColorMode) : "system";
  } catch {
    return "system";
  }
}

function prefersDark(): boolean {
  return typeof matchMedia === "function" && matchMedia(DARK).matches;
}

interface ColorModeValue {
  /** What the person chose. */
  mode: ColorMode;
  /** What is shown: the choice, or for system the operating system's. */
  resolved: "light" | "dark";
  setMode: (mode: ColorMode) => void;
}

const ColorModeContext = createContext<ColorModeValue | null>(null);

/**
 * The colour mode of a static app: no server render has to agree with it, so the stored choice is the state's first
 * value and the first render is already in the right mode. The design system's `<Theme mode>` applies it (and tells
 * the document, for the browser's own controls); this holds the choice, follows the operating system for system,
 * and writes the choice back. No inline script, no cookie.
 */
export function ColorModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ColorMode>(() => readStoredColorMode());
  const [dark, setDark] = useState(prefersDark);

  useEffect(() => {
    if (typeof matchMedia !== "function") return;
    const query = matchMedia(DARK);
    const follow = () => setDark(query.matches);
    follow();
    query.addEventListener("change", follow);
    return () => query.removeEventListener("change", follow);
  }, []);

  // Another tab's choice reaches this one.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === COLOR_MODE_KEY || event.key === null) setModeState(readStoredColorMode());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const setMode = useCallback((next: ColorMode) => {
    setModeState(next);
    try {
      browserStorage()?.setItem(COLOR_MODE_KEY, next);
    } catch {
      // Not stored (a quota, a private window): it still applies for the visit.
    }
  }, []);

  const value = useMemo<ColorModeValue>(
    () => ({ mode, resolved: mode === "system" ? (dark ? "dark" : "light") : mode, setMode }),
    [mode, dark, setMode],
  );
  return <ColorModeContext.Provider value={value}>{children}</ColorModeContext.Provider>;
}

/** The colour mode and a way to change it; inside ModuleProviders. */
export function useColorMode(): ColorModeValue {
  const value = useContext(ColorModeContext);
  if (!value) throw new Error("useColorMode must be used inside ColorModeProvider (ModuleProviders has one).");
  return value;
}
