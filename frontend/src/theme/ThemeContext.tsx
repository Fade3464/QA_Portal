import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

export type ThemeMode = 'light' | 'dark' | 'system';
export type ThemePresetId = 'calllens' | 'ant_blue' | 'geek_blue' | 'purple' | 'cyan' | 'emerald' | 'magenta' | 'volcano' | 'gold' | 'neutral';

export interface ThemePreferences {
  mode: ThemeMode;
  preset: ThemePresetId;
  compact: boolean;
}

export const THEME_PRESETS: Array<{
  id: ThemePresetId;
  name: string;
  description: string;
  primary: string;
  secondary: string;
  radius: number;
}> = [
  { id: 'calllens', name: 'CallLens', description: 'Our signature blue and teal', primary: '#087fdf', secondary: '#12c7bd', radius: 10 },
  { id: 'ant_blue', name: 'Ant Blue', description: 'Clear and familiar', primary: '#1677ff', secondary: '#69b1ff', radius: 8 },
  { id: 'geek_blue', name: 'Geek Blue', description: 'Focused indigo', primary: '#2f54eb', secondary: '#85a5ff', radius: 10 },
  { id: 'purple', name: 'Purple', description: 'Confident and expressive', primary: '#722ed1', secondary: '#b37feb', radius: 12 },
  { id: 'cyan', name: 'Cyan', description: 'Cool and precise', primary: '#08979c', secondary: '#5cdbd3', radius: 10 },
  { id: 'emerald', name: 'Emerald', description: 'Calm and balanced', primary: '#168f67', secondary: '#5fd3aa', radius: 12 },
  { id: 'magenta', name: 'Magenta', description: 'Distinct and energetic', primary: '#c41d7f', secondary: '#f08bc2', radius: 12 },
  { id: 'volcano', name: 'Volcano', description: 'Warm and decisive', primary: '#d84a1b', secondary: '#ff9c6e', radius: 8 },
  { id: 'gold', name: 'Gold', description: 'Warm and premium', primary: '#ad6800', secondary: '#ffd666', radius: 10 },
  { id: 'neutral', name: 'Slate', description: 'Quiet and understated', primary: '#526078', secondary: '#94a3b8', radius: 8 },
];

interface ThemeContextValue extends ThemePreferences {
  resolvedMode: 'light' | 'dark';
  primaryColor: string;
  secondaryColor: string;
  borderRadius: number;
  setMode: (mode: ThemeMode) => void;
  setPreset: (preset: ThemePresetId) => void;
  setCompact: (compact: boolean) => void;
  setPreferences: (preferences: ThemePreferences) => void;
  toggleMode: () => void;
  resetTheme: () => void;
}

const STORAGE_KEY = 'calllens-appearance-v3';
export const DEFAULT_THEME: ThemePreferences = { mode: 'system', preset: 'calllens', compact: false };
const ThemeContext = createContext<ThemeContextValue | null>(null);

function isMode(value: unknown): value is ThemeMode {
  return value === 'light' || value === 'dark' || value === 'system';
}

function isPreset(value: unknown): value is ThemePresetId {
  return THEME_PRESETS.some((preset) => preset.id === value);
}

function systemPrefersDark() {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function readPreferences(): ThemePreferences {
  if (typeof window === 'undefined') return DEFAULT_THEME;
  try {
    const saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '{}') as Partial<ThemePreferences>;
    return {
      mode: isMode(saved.mode) ? saved.mode : DEFAULT_THEME.mode,
      preset: isPreset(saved.preset) ? saved.preset : DEFAULT_THEME.preset,
      compact: typeof saved.compact === 'boolean' ? saved.compact : DEFAULT_THEME.compact,
    };
  } catch {
    return DEFAULT_THEME;
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preferences, updatePreferences] = useState<ThemePreferences>(readPreferences);
  const [systemDark, setSystemDark] = useState(systemPrefersDark);
  const resolvedMode = preferences.mode === 'system' ? (systemDark ? 'dark' : 'light') : preferences.mode;
  const selectedPreset = THEME_PRESETS.find((item) => item.id === preferences.preset) ?? THEME_PRESETS[0];

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
    document.documentElement.style.setProperty('--qa-primary', selectedPreset.primary);
    document.documentElement.style.setProperty('--qa-secondary', selectedPreset.secondary);
    document.documentElement.style.colorScheme = resolvedMode;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', resolvedMode === 'dark' ? '#10131a' : '#f5f7fb');
  }, [preferences, resolvedMode, selectedPreset]);

  const value = useMemo<ThemeContextValue>(() => ({
    ...preferences,
    resolvedMode,
    primaryColor: selectedPreset.primary,
    secondaryColor: selectedPreset.secondary,
    borderRadius: selectedPreset.radius,
    setMode: (mode) => updatePreferences((current) => ({ ...current, mode })),
    setPreset: (preset) => updatePreferences((current) => ({ ...current, preset })),
    setCompact: (compact) => updatePreferences((current) => ({ ...current, compact })),
    setPreferences: updatePreferences,
    toggleMode: () => updatePreferences((current) => ({ ...current, mode: resolvedMode === 'dark' ? 'light' : 'dark' })),
    resetTheme: () => updatePreferences(DEFAULT_THEME),
  }), [preferences, resolvedMode, selectedPreset]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useThemeSettings() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error('useThemeSettings must be used inside ThemeProvider');
  return context;
}
