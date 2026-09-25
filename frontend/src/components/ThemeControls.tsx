import { MoonOutlined, SettingOutlined, SunOutlined } from '@ant-design/icons';
import { App as AntApp, Button, Space, Tooltip } from 'antd';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { api } from '../lib/api';
import { useThemeSettings } from '../theme/ThemeContext';

interface ThemeControlsProps {
  className?: string;
  showSettings?: boolean;
}

export function ThemeControls({ className = '', showSettings = true }: ThemeControlsProps) {
  const { message } = AntApp.useApp();
  const [savingMode, setSavingMode] = useState(false);
  const { user } = useAuth();
  const navigate = useNavigate();
  const { mode, resolvedMode, setMode } = useThemeSettings();
  const nextMode = resolvedMode === 'dark' ? 'light' : 'dark';

  const changeMode = async () => {
    if (savingMode) return;
    const previousMode = mode;
    setMode(nextMode);
    if (!user) return;
    setSavingMode(true);
    try {
      await api('/api/v1/auth/account/appearance/', { method: 'PATCH', body: JSON.stringify({ mode: nextMode }) });
    } catch (error) {
      setMode(previousMode);
      message.error(error instanceof Error ? error.message : 'Could not save color mode.');
    } finally {
      setSavingMode(false);
    }
  };

  return (
    <Space size={4} className={`theme-actions ${className}`.trim()}>
      <Tooltip title={`Switch to ${nextMode} mode`}>
        <Button type="text" shape="circle" className="header-icon-button" loading={savingMode} icon={resolvedMode === 'dark' ? <SunOutlined /> : <MoonOutlined />} onClick={() => void changeMode()} aria-label={`Switch to ${nextMode} mode`} />
      </Tooltip>
      {showSettings && user && <Tooltip title="Appearance settings"><Button type="text" shape="circle" className="header-icon-button" icon={<SettingOutlined />} onClick={() => navigate('/account?tab=appearance')} aria-label="Open appearance settings" /></Tooltip>}
    </Space>
  );
}
