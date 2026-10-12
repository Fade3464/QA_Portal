import { theme, type ConfigProviderProps, type ThemeConfig } from 'antd';

export type ThemePresetId = 'default' | 'mui' | 'shadcn' | 'glass' | 'geek';
export const THEME_PRESETS: { id: ThemePresetId; name: string; description: string; primary: string; radius: number }[] = [
  { id: 'default', name: 'Default', description: 'Classic Ant Design', primary: '#1668dc', radius: 6 },
  { id: 'mui', name: 'MUI', description: 'Material surfaces and elevation', primary: '#1976d2', radius: 4 },
  { id: 'shadcn', name: 'shadcn', description: 'Quiet neutrals and crisp borders', primary: '#262626', radius: 10 },
  { id: 'glass', name: 'Glass', description: 'Clear content and frosted navigation', primary: '#1668dc', radius: 12 },
  { id: 'geek', name: 'Geek', description: 'Terminal green and sharp edges', primary: '#39ff14', radius: 0 },
];

// Adapted from Ant Design's MIT-licensed homepage ThemePreview presets.
// https://github.com/ant-design/ant-design/tree/master/.dumi/pages/index/components/ThemePreview/previewThemes
// Keep mode independent: the upstream MUI/shadcn/glass examples are light-only.
export function createWorkspaceTheme(preset: ThemePresetId, dark: boolean, compact: boolean): ConfigProviderProps {
  const style = THEME_PRESETS.find((item) => item.id === preset) ?? THEME_PRESETS[0];
  const primary = preset === 'shadcn' ? (dark ? '#fafafa' : '#262626')
    : preset === 'mui' && dark ? '#90caf9'
    : preset === 'geek' && !dark ? '#237b13' : style.primary;
  const backgrounds = {
    default: dark ? ['#10131a', '#181c25', '#202631'] : ['#f5f7fb', '#ffffff', '#f0f3f8'],
    mui: dark ? ['#121212', '#1e1e1e', '#292929'] : ['#f5f5f5', '#ffffff', '#eeeeee'],
    shadcn: dark ? ['#09090b', '#18181b', '#27272a'] : ['#fafafa', '#ffffff', '#f4f4f5'],
    glass: dark ? ['#101722', '#19222e', '#242f3d'] : ['#f3f5f8', '#ffffff', '#edf1f6'],
    geek: dark ? ['#030603', '#091109', '#132313'] : ['#f2f7ef', '#fcfefb', '#e7efdf'],
  }[preset];
  const [bg, surface, soft] = backgrounds;
  const config: ThemeConfig = {
    inherit: false,
    algorithm: [dark ? theme.darkAlgorithm : theme.defaultAlgorithm, ...(compact ? [theme.compactAlgorithm] : [])],
    token: {
      colorPrimary: primary, colorInfo: primary,
      colorBgBase: dark ? '#000000' : '#ffffff',
      colorTextBase: dark ? '#ffffff' : '#000000',
      colorBgLayout: bg, colorBgContainer: surface, colorBgElevated: surface,
      colorFillAlter: soft,
      // Statistic titles, empty states and Typography secondary text use this
      // alias. They carry information and must remain readable on content panels.
      colorTextDescription: preset === 'shadcn' ? (dark ? '#a1a1aa' : '#525252')
        : dark ? 'rgba(255,255,255,0.65)' : 'rgba(0,0,0,0.65)',
      ...(dark && (preset === 'default' || preset === 'glass') ? {
        colorPrimaryText: '#8ab4f8', colorPrimaryTextHover: '#b1cefa', colorPrimaryTextActive: '#6fa2ef',
        colorLink: '#8ab4f8', colorLinkHover: '#b1cefa', colorLinkActive: '#6fa2ef',
      } : {}),
      ...(preset === 'mui' && !dark ? {
        colorPrimaryText: '#1565c0', colorPrimaryTextHover: '#0d47a1', colorPrimaryTextActive: '#0d47a1',
        colorLink: '#1565c0', colorLinkHover: '#0d47a1', colorLinkActive: '#0d47a1',
      } : {}),
      borderRadius: style.radius, borderRadiusLG: preset === 'shadcn' ? 14 : style.radius,
      ...(preset === 'geek' ? { borderRadiusSM: 0, borderRadiusXS: 0, lineWidth: 2 } : {}),
      fontFamily: preset === 'mui' ? 'Roboto, Helvetica, Arial, sans-serif'
        : preset === 'geek' ? '"SFMono-Regular", Consolas, "Liberation Mono", monospace'
        : "'DM Sans', ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      ...(preset === 'mui' ? { colorSuccess: '#2e7d32', colorWarning: '#ed6c02', colorError: '#d32f2f', fontWeightStrong: 500 } : {}),
      ...(preset === 'shadcn' ? {
        colorText: dark ? '#fafafa' : '#262626', colorTextSecondary: dark ? '#a1a1aa' : '#525252',
        colorBorder: dark ? '#3f3f46' : '#e5e5e5', colorBorderSecondary: dark ? '#27272a' : '#f0f0f0',
        colorPrimaryBg: soft, colorPrimaryBgHover: soft, colorPrimaryHover: dark ? '#e4e4e7' : '#404040',
        colorPrimaryActive: dark ? '#d4d4d8' : '#171717', colorPrimaryText: primary,
        colorPrimaryTextHover: primary, colorPrimaryTextActive: primary,
      } : {}),
      ...(preset === 'geek' ? { colorText: dark ? '#b9edb0' : '#193819', colorBorder: dark ? '#30512b' : '#adc7a2' } : {}),
      boxShadow: preset === 'mui' ? '0 2px 1px -1px #0003, 0 1px 1px #0002, 0 1px 3px #0002'
        : preset === 'geek' ? `0 0 8px ${primary}24`
        : dark ? '0 8px 28px #0004' : '0 1px 3px #0001, 0 1px 2px #0001',
    },
  };
  const token = theme.getDesignToken(config);
  config.components = {
    Layout: { bodyBg: 'transparent', headerBg: surface, siderBg: surface, lightSiderBg: surface, lightTriggerBg: surface },
    Menu: { itemBg: 'transparent', subMenuItemBg: 'transparent', itemColor: token.colorTextSecondary,
      itemHoverColor: token.colorText, itemHoverBg: soft, itemSelectedBg: token.colorPrimaryBg,
      itemSelectedColor: preset === 'geek' ? primary : token.colorPrimaryText,
      itemBorderRadius: style.radius, itemHeight: compact ? 38 : 44,
      itemMarginBlock: 2, itemMarginInline: 12, iconSize: 17, collapsedIconSize: 17, iconMarginInlineEnd: 12 },
    Card: { headerBg: 'transparent', headerFontSize: 15 },
    Button: { fontWeight: preset === 'mui' ? 500 : 600,
      primaryColor: dark && (preset === 'shadcn' || preset === 'geek' || preset === 'mui') ? '#09090b' : '#ffffff',
      primaryShadow: preset === 'mui' ? token.boxShadow : 'none', defaultShadow: 'none',
      ...(preset === 'shadcn' ? { borderRadius: 6 } : {}) },
    Input: { ...(preset === 'shadcn' ? { borderRadius: 6, activeShadow: `0 0 0 2px ${token.colorBorder}` } : {}) },
    Table: { headerBg: soft, headerColor: token.colorTextSecondary,
      cellPaddingBlock: compact ? 8 : 12, cellFontSize: 13, rowHoverBg: soft,
      bodySortBg: surface, headerSortActiveBg: soft, headerSortHoverBg: soft, fixedHeaderSortActiveBg: soft },
    Statistic: { titleFontSize: 12, contentFontSize: 29 },
  };
  return {
    theme: config,
    card: { classNames: { root: `workspace-card workspace-card--${preset}` } },
    button: { classNames: { root: `workspace-button workspace-button--${preset}` } },
    modal: { styles: { container: preset === 'glass'
      ? { background: 'var(--qa-header)', backdropFilter: 'var(--qa-overlay-blur, none)' } : {} } },
  };
}
