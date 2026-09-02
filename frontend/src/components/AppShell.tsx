import {
  AppstoreOutlined,
  AuditOutlined,
  BarChartOutlined,
  BellOutlined,
  CustomerServiceOutlined,
  DashboardOutlined,
  DownOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  SettingOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import { Avatar, Badge, Button, Dropdown, Layout, Menu, Tag, Tooltip, Typography, type MenuProps } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { useThemeSettings } from '../theme/ThemeContext';
import { BrandMark } from './BrandMark';
import { ThemeControls } from './ThemeControls';

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

export function AppShell() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const { resolvedMode } = useThemeSettings();
  const [collapsed, setCollapsed] = useState(false);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws/notifications/`);
    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    return () => socket.close();
  }, []);

  const items = useMemo<MenuProps['items']>(() => {
    const all = [
      { key: '/', icon: <DashboardOutlined />, label: <Link to="/">Command center</Link> },
      { key: '/queue', icon: <AuditOutlined />, label: <Link to="/queue">Review queue</Link> },
      { key: '/calls', icon: <CustomerServiceOutlined />, label: <Link to="/calls">Call library</Link> },
      { key: '/team', icon: <TeamOutlined />, label: <Link to="/team">Team performance</Link>, roles: ['team_leader', 'project_manager', 'supervisor', 'administrator'] },
      { key: '/insights', icon: <BarChartOutlined />, label: <Link to="/insights">Quality insights</Link>, roles: ['project_manager', 'supervisor', 'administrator'] },
      { key: '/admin', icon: <SettingOutlined />, label: <Link to="/admin">Administration</Link>, roles: ['administrator'] },
    ];
    return all.filter((item) => !item.roles || item.roles.includes(user?.role ?? ''));
  }, [user?.role]);

  const accountMenu: MenuProps['items'] = [
    { key: 'profile', label: 'My profile', icon: <AppstoreOutlined />, disabled: true },
    { type: 'divider' },
    { key: 'logout', label: 'Sign out', icon: <LogoutOutlined />, danger: true, onClick: async () => { await logout(); navigate('/login'); } },
  ];
  const initials = `${user?.first_name?.[0] ?? ''}${user?.last_name?.[0] ?? ''}`.toUpperCase() || 'U';

  return (
    <Layout className="app-layout" hasSider>
      <Sider width={264} collapsedWidth={76} collapsed={collapsed} trigger={null} breakpoint="lg" onBreakpoint={setCollapsed} className="app-sider" theme={resolvedMode}>
        <div className="sider-brand"><BrandMark compact={collapsed} /></div>
        {!collapsed && <Text className="nav-label">WORKSPACE</Text>}
        <Menu mode="inline" theme={resolvedMode} selectedKeys={[location.pathname]} items={items} className="app-menu" />
        <div className="sider-foot">
          {!collapsed && <div className="workspace-card"><span className="workspace-card__icon"><AppstoreOutlined /></span><span><small>Active branch</small><strong>{user?.branch?.name ?? 'System-wide'}</strong></span></div>}
          <Tooltip title={collapsed ? 'Expand navigation' : 'Collapse navigation'} placement="right">
            <Button type="text" className="collapse-button" icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} onClick={() => setCollapsed((value) => !value)} aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'} />
          </Tooltip>
        </div>
      </Sider>
      <Layout>
        <Header className="app-header">
          <div className="header-context">
            <Text type="secondary">{user?.company?.name ?? 'System administration'}</Text>
            <strong>{user?.branch?.name ?? 'All organizations'}</strong>
          </div>
          <div className="header-actions">
            <Tag color={connected ? 'success' : 'default'} className="live-status"><span className={`live-dot ${connected ? '' : 'live-dot--muted'}`} />{connected ? 'Live' : 'Connecting'}</Tag>
            <Badge dot><Button type="text" icon={<BellOutlined />} aria-label="Notifications" /></Badge>
            <ThemeControls />
            <Dropdown menu={{ items: accountMenu }} trigger={['click']} placement="bottomRight">
              <button className="account-button" type="button">
                <Avatar size={38}>{initials}</Avatar>
                <span className="account-button__copy"><strong>{user?.name}</strong><small>{user?.role_label}</small></span>
                <DownOutlined />
              </button>
            </Dropdown>
          </div>
        </Header>
        <Content className="app-content"><Outlet /></Content>
      </Layout>
    </Layout>
  );
}
