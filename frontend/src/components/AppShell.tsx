import {
  AppstoreOutlined,
  AuditOutlined,
  BarChartOutlined,
  BellOutlined,
  CheckOutlined,
  CustomerServiceOutlined,
  DashboardOutlined,
  DownOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  SettingOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import { App as AntApp, Avatar, Badge, Button, Dropdown, Empty, Layout, Menu, Popover, Tag, Tooltip, Typography, type MenuProps } from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { api } from '../lib/api';
import type { NotificationResponse, SystemNotification } from '../types';
import { BrandMark } from './BrandMark';
import { ThemeControls } from './ThemeControls';

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

export function AppShell() {
  const { notification: toast } = AntApp.useApp();
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  const [connection, setConnection] = useState<'connecting' | 'live' | 'offline'>('connecting');
  const [notifications, setNotifications] = useState<SystemNotification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [notificationsLoading, setNotificationsLoading] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);

  const loadNotifications = useCallback(async () => {
    if (!user?.is_superuser) return;
    setNotificationsLoading(true);
    try {
      const result = await api<NotificationResponse>('/api/v1/notifications/');
      setNotifications(result.results);
      setUnreadCount(result.unread_count);
    } catch {
      // Connection state communicates outages without interrupting the workspace.
    } finally {
      setNotificationsLoading(false);
    }
  }, [user?.is_superuser]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadNotifications(), 0);
    return () => window.clearTimeout(timer);
  }, [loadNotifications]);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retryTimer = 0;
    let stopped = false;
    const connect = () => {
      if (stopped) return;
      setConnection('connecting');
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      socket = new WebSocket(`${protocol}//${window.location.host}/ws/notifications/`);
      socket.onopen = () => {
        setConnection('live');
        void loadNotifications();
      };
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as { type?: string; notification?: SystemNotification };
          if (payload.type === 'notification.updated' && payload.notification) {
            const incoming = { ...payload.notification, is_read: false };
            setNotifications((current) => {
              const alreadyUnread = current.some((item) => item.id === incoming.id && !item.is_read);
              if (!alreadyUnread) setUnreadCount((count) => count + 1);
              return [incoming, ...current.filter((item) => item.id !== incoming.id)].slice(0, 50);
            });
            toast.warning({ message: incoming.title, description: incoming.message, placement: 'topRight' });
          } else if (payload.type === 'notification.resolved' && payload.notification) {
            setNotifications((current) => current.filter((item) => item.id !== payload.notification?.id));
            void loadNotifications();
          }
        } catch {
          // Ignore malformed frames and keep the reconnect loop alive.
        }
      };
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
  }, [loadNotifications, toast]);

  const markRead = async (item: SystemNotification) => {
    if (!item.is_read) {
      setNotifications((current) => current.map((entry) => entry.id === item.id ? { ...entry, is_read: true } : entry));
      setUnreadCount((current) => Math.max(0, current - 1));
      try { await api(`/api/v1/notifications/${item.id}/read/`, { method: 'POST' }); } catch { void loadNotifications(); }
    }
  };

  const markAllRead = async () => {
    setNotifications((current) => current.map((item) => ({ ...item, is_read: true })));
    setUnreadCount(0);
    try { await api('/api/v1/notifications/read-all/', { method: 'POST' }); } catch { void loadNotifications(); }
  };

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
  const notificationPanel = (
    <div className="notification-panel">
      <div className="notification-panel__header">
        <span><strong>System notifications</strong><small>{unreadCount ? `${unreadCount} need attention` : 'You are all caught up'}</small></span>
        {unreadCount > 0 && <Button type="link" size="small" icon={<CheckOutlined />} onClick={() => void markAllRead()}>Read all</Button>}
      </div>
      <div className={`notification-panel__list${notificationsLoading ? ' notification-panel__list--loading' : ''}`}>
        {notifications.length ? notifications.map((item) => (
          <button key={item.id} type="button" className={`notification-item${item.is_read ? '' : ' notification-item--unread'}`} onClick={() => { void markRead(item); setNotificationsOpen(false); navigate('/admin'); }}>
            <span className={`notification-item__indicator notification-item__indicator--${item.severity}`} />
            <span className="notification-item__copy"><strong>{item.title}</strong><span>{item.message}</span><small>{item.occurrences > 1 ? `${item.occurrences} calls · ` : ''}{dayjs(item.updated_at).format('DD MMM, h:mm A')}</small></span>
          </button>
        )) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No active notifications" />}
      </div>
    </div>
  );

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
            {user?.is_superuser ? <Popover content={notificationPanel} trigger="click" placement="bottomRight" open={notificationsOpen} onOpenChange={(open) => { setNotificationsOpen(open); if (open) void loadNotifications(); }} styles={{ content: { padding: 0 } }}><Badge count={unreadCount} size="small" overflowCount={99}><Button type="text" shape="circle" className="header-icon-button" icon={<BellOutlined />} aria-label={`${unreadCount} unread notifications`} /></Badge></Popover> : <Tooltip title="No new notifications"><Button type="text" shape="circle" className="header-icon-button" icon={<BellOutlined />} aria-label="Notifications" /></Tooltip>}
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
