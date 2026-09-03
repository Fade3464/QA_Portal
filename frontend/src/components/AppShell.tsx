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
import { Avatar, Button, Dropdown, Layout, Menu, Tag, Tooltip, Typography, type MenuProps } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { BrandMark } from './BrandMark';
import { ThemeControls } from './ThemeControls';

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

export function AppShell() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  const [connection, setConnection] = useState<'connecting' | 'live' | 'offline'>('connecting');

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retryTimer = 0;
    let stopped = false;
    const connect = () => {
      if (stopped) return;
      setConnection('connecting');
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      socket = new WebSocket(`${protocol}//${window.location.host}/ws/notifications/`);
      socket.onopen = () => setConnection('live');
      socket.onclose = () => {
        if (stopped) return;
        setConnection('offline');
        retryTimer = window.setTimeout(connect, 3000);
      };
      socket.onerror = () => socket?.close();
    };
    retryTimer = window.setTimeout(connect, 0);
    return () => {
      stopped = true;
      window.clearTimeout(retryTimer);
      socket?.close();
    };
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
      <Sider width={264} collapsedWidth={76} collapsed={collapsed} trigger={null} breakpoint="lg" onBreakpoint={setCollapsed} className="app-sider" theme="light">
        <div className="sider-brand"><BrandMark compact={collapsed} /></div>
        <div className={`sider-nav-header${collapsed ? ' sider-nav-header--collapsed' : ''}`}>
          {!collapsed && <Text className="nav-label">WORKSPACE</Text>}
          <Tooltip title={collapsed ? 'Expand navigation' : 'Collapse navigation'} placement="right">
            <Button
              type="text"
              shape="circle"
              className="collapse-button"
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setCollapsed((value) => !value)}
              aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
            />
          </Tooltip>
        </div>
        <Menu mode="inline" theme="light" selectedKeys={[location.pathname]} items={items} className="app-menu" classNames={{ itemIcon: 'app-menu__icon', itemContent: 'app-menu__content' }} />
        {!collapsed && (
          <div className="sider-foot">
            <div className="workspace-card"><span className="workspace-card__icon"><AppstoreOutlined /></span><span><small>Active branch</small><strong>{user?.branch?.name ?? 'System-wide'}</strong></span></div>
          </div>
        )}
      </Sider>
      <Layout className="app-main">
        <Header className="app-header">
          <div className="header-context">
            <Text type="secondary" className="header-context__company">{user?.company?.name ?? 'System administration'}</Text>
            <strong>{user?.branch?.name ?? 'All organizations'}</strong>
          </div>
          <div className="header-actions">
            <Tag color={connection === 'live' ? 'success' : connection === 'offline' ? 'error' : 'default'} className="live-status"><span className={`live-dot ${connection === 'live' ? '' : 'live-dot--muted'}`} />{connection === 'live' ? 'Live' : connection === 'offline' ? 'Offline' : 'Connecting'}</Tag>
            <Tooltip title="No new notifications"><Button type="text" shape="circle" className="header-icon-button" icon={<BellOutlined />} aria-label="Notifications" /></Tooltip>
            <ThemeControls />
            <Dropdown menu={{ items: accountMenu }} trigger={['click']} placement="bottomRight">
              <button className="account-button" type="button">
                <Avatar size={38} className="account-avatar">{initials}</Avatar>
                <span className="account-button__copy"><strong>{user?.name}</strong><small>{user?.role_label}</small></span>
                <DownOutlined className="account-chevron" />
              </button>
            </Dropdown>
          </div>
        </Header>
        <Content className="app-content"><Outlet /></Content>
      </Layout>
    </Layout>
  );
}
