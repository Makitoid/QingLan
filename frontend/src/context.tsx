import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import type { SiteSettings } from './api/types';
import { fetchSiteSettings, getStoredThemeMode, resolveIsDark, storeThemeMode, systemPrefersDark, type ThemeMode } from './theme';

/* ---------- site settings ---------- */

interface SettingsContextValue {
  settings: SiteSettings | null;
  preview: Partial<SiteSettings>;
  setPreview: (patch: Partial<SiteSettings>) => void;
  clearPreview: () => void;
  effective: SiteSettings | null;
  reload: () => Promise<void>;
}

const SettingsContext = createContext<SettingsContextValue | null>(null);

export function SettingsProvider({ children, initial }: { children: ReactNode; initial: SiteSettings | null }) {
  const [settings, setSettings] = useState<SiteSettings | null>(initial);
  const [preview, setPreviewState] = useState<Partial<SiteSettings>>({});

  const reload = useCallback(async () => {
    const next = await fetchSiteSettings();
    setSettings(next);
  }, []);

  const setPreview = useCallback((patch: Partial<SiteSettings>) => {
    setPreviewState((prev) => ({ ...prev, ...patch }));
  }, []);

  const clearPreview = useCallback(() => setPreviewState({}), []);

  const effective = useMemo(() => {
    if (!settings) return null;
    return { ...settings, ...preview };
  }, [settings, preview]);

  const value = useMemo(
    () => ({ settings, preview, setPreview, clearPreview, effective, reload }),
    [settings, preview, setPreview, clearPreview, effective, reload],
  );

  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export function useSettings(): SettingsContextValue {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error('useSettings must be used within SettingsProvider');
  return ctx;
}

/* ---------- theme mode ---------- */

interface ThemeModeContextValue {
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
  isDark: boolean;
}

const ThemeModeContext = createContext<ThemeModeContextValue | null>(null);

export function ThemeModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(() => getStoredThemeMode());
  const [systemDark, setSystemDark] = useState<boolean>(() => systemPrefersDark());

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  const setMode = useCallback((next: ThemeMode) => {
    setModeState(next);
    storeThemeMode(next);
  }, []);

  const isDark = mode === 'system' ? systemDark : mode === 'dark';

  const value = useMemo(() => ({ mode, setMode, isDark }), [mode, setMode, isDark]);

  return <ThemeModeContext.Provider value={value}>{children}</ThemeModeContext.Provider>;
}

export function useThemeMode(): ThemeModeContextValue {
  const ctx = useContext(ThemeModeContext);
  if (!ctx) throw new Error('useThemeMode must be used within ThemeModeProvider');
  return ctx;
}

export { resolveIsDark };
