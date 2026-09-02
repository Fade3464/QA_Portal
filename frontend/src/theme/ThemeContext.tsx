import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

export type ThemeMode = 'light' | 'dark' | 'system';

interface ThemePreferences {
  mode: ThemeMode;
  primaryColor: string;
  compact: boolean;
}

interface ThemeContextValue extends ThemePreferences {
  resolvedMode: 'light' | 'dark';
  setMode: (mode: ThemeMode) => void;
  setPrimaryColor: (color: string) => void;
  setCompact: (compact: boolean) => void;
  toggleMode: () => void;
  resetTheme: () => void;
}

const STORAGE_KEY = 'qa-portal-appearance-v2';

export const PRIMARY_COLORS = [
  { name: 'Ant blue', value: '#1677ff' },
  { name: 'Indigo', value: '#6157e8' },
  { name: 'Cyan', value: '#08979c' },
  { name: 'Emerald', value: '#0f9f76' },
  { name: 'Magenta', value: '#c41d7f' },
] as const;

const defaults: ThemePreferences = {
  mode: 'light',
  primaryColor: PRIMARY_COLORS[0].value,
  compact: false,
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

function systemPrefersDark() {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function readPreferences(): ThemePreferences {
  if (typeof window === 'undefined') return defaults;
  try {
    const saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '{}') as Partial<ThemePreferences>;
    const mode = saved.mode === 'light' || saved.mode === 'dark' || saved.mode === 'system' ? saved.mode : defaults.mode;
    const primaryColor = PRIMARY_COLORS.some((color) => color.value === saved.primaryColor) ? saved.primaryColor! : defaults.primaryColor;
    return { mode, primaryColor, compact: Boolean(saved.compact) };
  } catch {
    return defaults;
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preferences, setPreferences] = useState<ThemePreferences>(readPreferences);
  const [systemDark, setSystemDark] = useState(systemPrefersDark);
  const resolvedMode = preferences.mode === 'system' ? (systemDark ? 'dark' : 'light') : preferences.mode;

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const handleChange = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    media.addEventListener('change', handleChange);
    return () => media.removeEventListener('change', handleChange);
  }, []);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
    document.documentElement.dataset.theme = resolvedMode;
    document.documentElement.dataset.density = preferences.compact ? 'compact' : 'comfortable';
    document.documentElement.style.setProperty('--qa-primary', preferences.primaryColor);
    document.documentElement.style.colorScheme = resolvedMode;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', resolvedMode === 'dark' ? '#10131a' : '#f5f7fb');
  }, [preferences, resolvedMode]);

  const value = useMemo<ThemeContextValue>(() => ({
    ...preferences,
    resolvedMode,
    setMode: (mode) => setPreferences((current) => ({ ...current, mode })),
    setPrimaryColor: (primaryColor) => setPreferences((current) => ({ ...current, primaryColor })),
    setCompact: (compact) => setPreferences((current) => ({ ...current, compact })),
    toggleMode: () => setPreferences((current) => ({ ...current, mode: resolvedMode === 'dark' ? 'light' : 'dark' })),
    resetTheme: () => setPreferences(defaults),
  }), [preferences, resolvedMode]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useThemeSettings() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error('useThemeSettings must be used inside ThemeProvider');
  return context;
}
