import {
  BgColorsOutlined,
  BulbOutlined,
  DesktopOutlined,
  MoonOutlined,
  SettingOutlined,
  SunOutlined,
  UndoOutlined,
} from '@ant-design/icons';
import { Button, Divider, Drawer, Segmented, Space, Switch, Tooltip, Typography } from 'antd';
import { useState, type CSSProperties } from 'react';
import { PRIMARY_COLORS, useThemeSettings, type ThemeMode } from '../theme/ThemeContext';

const { Paragraph, Text, Title } = Typography;

export function ThemeControls({ className = '' }: { className?: string }) {
  const [open, setOpen] = useState(false);
  const { mode, resolvedMode, primaryColor, compact, setMode, setPrimaryColor, setCompact, toggleMode, resetTheme } = useThemeSettings();
  const nextMode = resolvedMode === 'dark' ? 'light' : 'dark';

  return (
    <>
      <Space size={4} className={`theme-actions ${className}`.trim()}>
        <Tooltip title={`Switch to ${nextMode} mode`}>
          <Button
            type="text"
            shape="circle"
            className="header-icon-button"
            icon={resolvedMode === 'dark' ? <SunOutlined /> : <MoonOutlined />}
            onClick={toggleMode}
            aria-label={`Switch to ${nextMode} mode`}
          />
        </Tooltip>
        <Tooltip title="Appearance settings">
          <Button type="text" shape="circle" className="header-icon-button" icon={<SettingOutlined />} onClick={() => setOpen(true)} aria-label="Open appearance settings" />
        </Tooltip>
      </Space>

      <Drawer
        title={<Space><BgColorsOutlined /><span>Appearance</span></Space>}
        placement="right"
        size="default"
        open={open}
        onClose={() => setOpen(false)}
        extra={<Button type="text" icon={<UndoOutlined />} onClick={resetTheme}>Reset</Button>}
      >
        <div className="theme-panel">
          <div>
            <Title level={5}>Color mode</Title>
            <Paragraph type="secondary">Follow your device or choose a fixed appearance.</Paragraph>
            <Segmented<ThemeMode>
              block
              value={mode}
              onChange={setMode}
              options={[
                { value: 'light', label: <Space size={6}><SunOutlined />Light</Space> },
                { value: 'dark', label: <Space size={6}><MoonOutlined />Dark</Space> },
                { value: 'system', label: <Space size={6}><DesktopOutlined />System</Space> },
              ]}
            />
          </div>

          <Divider />

          <div>
            <Title level={5}>Accent color</Title>
            <Paragraph type="secondary">Choose the primary color used for actions and focus states.</Paragraph>
            <div className="theme-swatches" role="radiogroup" aria-label="Accent color">
              {PRIMARY_COLORS.map((color) => (
                <Tooltip title={color.name} key={color.value}>
                  <button
                    type="button"
                    className={`theme-swatch ${primaryColor === color.value ? 'theme-swatch--selected' : ''}`}
                    style={{ '--swatch-color': color.value } as CSSProperties}
                    onClick={() => setPrimaryColor(color.value)}
                    role="radio"
                    aria-checked={primaryColor === color.value}
                    aria-label={color.name}
                  >
                    <span />
                  </button>
                </Tooltip>
              ))}
            </div>
          </div>

          <Divider />

          <div className="theme-density">
            <span>
              <Title level={5}>Compact density</Title>
              <Text type="secondary">Fit more information on each screen.</Text>
            </span>
            <Switch checked={compact} onChange={setCompact} aria-label="Use compact interface density" />
          </div>

          <div className="theme-preview">
            <span className="theme-preview__icon"><BulbOutlined /></span>
            <span><strong>Preview updates instantly</strong><small>Your preference is saved on this device.</small></span>
          </div>
        </div>
      </Drawer>
    </>
  );
}
