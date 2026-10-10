import { createContext, useCallback, useLayoutEffect, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { theme, type ConfigProviderProps } from 'antd';
import { createWorkspaceTheme, THEME_PRESETS, type ThemePresetId } from './styles';
export type ThemeMode = 'light' | 'dark' | 'system';
export { THEME_PRESETS };
export type { ThemePresetId };

export interface ThemePreferences {
  mode: ThemeMode;
  preset: ThemePresetId;
  compact: boolean;
}

interface ThemeContextValue extends ThemePreferences {
  resolvedMode: 'light' | 'dark';
  providerProps: ConfigProviderProps;
  setMode: (mode: ThemeMode) => void;
  setPreset: (preset: ThemePresetId) => void;
  setCompact: (compact: boolean) => void;
  setPreferences: (preferences: ThemePreferences) => void;
  toggleMode: () => void;
  resetTheme: () => void;
}

const STORAGE_KEY = 'calllens-appearance-v3';
export const DEFAULT_THEME: ThemePreferences = { mode: 'system', preset: 'default', compact: false };
const ThemeContext = createContext<ThemeContextValue | null>(null);

function isMode(value: unknown): value is ThemeMode {
  return value === 'light' || value === 'dark' || value === 'system';
}

function isPreset(value: unknown): value is ThemePresetId {
  return THEME_PRESETS.some((preset) => preset.id === value);
}

export function normalizePreferences(saved: Partial<ThemePreferences>): ThemePreferences {
  return {
    mode: isMode(saved.mode) ? saved.mode : DEFAULT_THEME.mode,
    preset: isPreset(saved.preset) ? saved.preset : DEFAULT_THEME.preset,
    compact: typeof saved.compact === 'boolean' ? saved.compact : DEFAULT_THEME.compact,
  };
}

function systemPrefersDark() {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function readPreferences(): ThemePreferences {
  if (typeof window === 'undefined') return DEFAULT_THEME;
  try {
    const saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '{}') as Partial<ThemePreferences>;
    return normalizePreferences(saved);
  } catch {
    return DEFAULT_THEME;
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preferences, updatePreferences] = useState<ThemePreferences>(readPreferences);
  const [systemDark, setSystemDark] = useState(systemPrefersDark);
  const resolvedMode = preferences.mode === 'system' ? (systemDark ? 'dark' : 'light') : preferences.mode;
  const providerProps = useMemo(() => createWorkspaceTheme(preferences.preset, resolvedMode === 'dark', preferences.compact), [preferences.preset, resolvedMode, preferences.compact]);
  const setPreferences = useCallback((next: ThemePreferences) => updatePreferences(normalizePreferences(next)), []);

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const handleChange = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    media.addEventListener('change', handleChange);
    return () => media.removeEventListener('change', handleChange);
  }, []);

  useEffect(() => {
    try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences)); }
    catch { /* Browser storage can be unavailable; server preferences still work. */ }
  }, [preferences]);

  useLayoutEffect(() => {
    const token = theme.getDesignToken(providerProps.theme);
    const root = document.documentElement;
    root.dataset.theme = resolvedMode;
    root.dataset.style = preferences.preset;
    root.dataset.density = preferences.compact ? 'compact' : 'comfortable';
    const glass = preferences.preset === 'glass';
    const variables: Record<string, string> = {
      primary: token.colorPrimary, secondary: token.colorPrimaryHover,
      'on-primary': providerProps.theme?.components?.Button?.primaryColor ?? '#ffffff',
      bg: token.colorBgLayout,
      'page-background': glass
        ? `radial-gradient(ellipse at 10% 0%, ${token.colorPrimary}22, transparent 55%), radial-gradient(ellipse at 90% 70%, #8b5cf622, transparent 55%), ${token.colorBgLayout}`
        : token.colorBgLayout,
      surface: glass ? `color-mix(in srgb, ${token.colorBgContainer} 88%, transparent)` : token.colorBgContainer,
      'surface-soft': token.colorFillAlter, 'surface-raised': token.colorBgElevated,
      text: token.colorText, 'text-muted': token.colorTextSecondary, 'text-faint': token.colorTextTertiary,
      border: token.colorBorder, 'border-soft': token.colorBorderSecondary,
      hover: token.colorFillAlter, header: `color-mix(in srgb, ${token.colorBgContainer} 92%, transparent)`,
      shadow: token.boxShadow, radius: `${token.borderRadius}px`, 'radius-lg': `${token.borderRadiusLG}px`,
      font: token.fontFamily,
    };
    for (const [name, value] of Object.entries(variables)) root.style.setProperty(`--qa-${name}`, value);
    root.style.colorScheme = resolvedMode;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', token.colorBgLayout);
  }, [preferences.preset, preferences.compact, resolvedMode, providerProps]);

  const value = useMemo<ThemeContextValue>(() => ({
    ...preferences,
    resolvedMode,
    providerProps,
    setMode: (mode) => updatePreferences((current) => ({ ...current, mode })),
    setPreset: (preset) => updatePreferences((current) => ({ ...current, preset })),
    setCompact: (compact) => updatePreferences((current) => ({ ...current, compact })),
    setPreferences,
    toggleMode: () => updatePreferences((current) => ({ ...current, mode: resolvedMode === 'dark' ? 'light' : 'dark' })),
    resetTheme: () => updatePreferences(DEFAULT_THEME),
  }), [preferences, resolvedMode, providerProps, setPreferences]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useThemeSettings() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error('useThemeSettings must be used inside ThemeProvider');
  return context;
}
