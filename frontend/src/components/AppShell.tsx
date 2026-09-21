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
  UserOutlined,
} from '@ant-design/icons';
import { App as AntApp, Avatar, Badge, Button, Dropdown, Empty, Layout, Menu, Popover, Tag, Tooltip, Typography, type MenuProps } from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { api } from '../lib/api';
import { browserNotificationPermission, requestBrowserNotificationPermission, showBrowserNotification } from '../lib/browserNotifications';
import { appDate } from '../lib/datetime';
import type { CallReservation, NotificationResponse, SystemNotification } from '../types';
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
  const [browserPermission, setBrowserPermission] = useState<NotificationPermission | 'unsupported'>(() => browserNotificationPermission());
  const isQa = user?.role === 'qa' && !user.is_superuser;

  const enableBrowserNotifications = useCallback(async () => {
    try {
      setBrowserPermission(await requestBrowserNotificationPermission());
    } catch {
      setBrowserPermission(browserNotificationPermission());
    }
  }, []);

  useEffect(() => {
    if (!user || browserNotificationPermission() !== 'default') return;
    const timer = window.setTimeout(() => void enableBrowserNotifications(), 500);
    return () => window.clearTimeout(timer);
  }, [enableBrowserNotifications, user]);

  const loadNotifications = useCallback(async () => {
    if (!user) return;
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
  }, [user]);

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
          const payload = JSON.parse(event.data) as {
            type?: string;
            notification?: SystemNotification;
            call_id?: string;
            reservation?: CallReservation | null;
          };
          if (payload.type === 'notification.updated' && payload.notification) {
            const incoming = { ...payload.notification, is_read: false };
            setNotifications((current) => {
              const alreadyUnread = current.some((item) => item.id === incoming.id && !item.is_read);
              if (!alreadyUnread) setUnreadCount((count) => count + 1);
              return [incoming, ...current.filter((item) => item.id !== incoming.id)].slice(0, 50);
            });
            const toastOptions = { message: incoming.title, description: incoming.message, placement: 'topRight' as const };
            if (incoming.severity === 'error') toast.error(toastOptions);
            else if (incoming.severity === 'warning') toast.warning(toastOptions);
            else toast.info(toastOptions);
            showBrowserNotification(incoming, () => {
              const target = incoming.metadata.target_path;
              navigate(target?.startsWith('/') && !target.startsWith('//') ? target : (user?.is_superuser ? '/admin' : '/queue'));
              setNotificationsOpen(false);
              setNotifications((current) => {
                if (current.some((item) => item.id === incoming.id && !item.is_read)) {
                  setUnreadCount((count) => Math.max(0, count - 1));
                }
                return current.map((item) => item.id === incoming.id ? { ...item, is_read: true } : item);
              });
              void api(`/api/v1/notifications/${incoming.id}/read/`, { method: 'POST' }).catch(() => void loadNotifications());
            });
          } else if (payload.type === 'notification.resolved' && payload.notification) {
            setNotifications((current) => current.filter((item) => item.id !== payload.notification?.id));
            void loadNotifications();
          } else if (payload.type === 'call.reservation' && payload.call_id) {
            window.dispatchEvent(new CustomEvent('qa:call-reservation', { detail: payload }));
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
  }, [loadNotifications, navigate, toast, user?.is_superuser]);

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
      { key: '/', icon: <DashboardOutlined />, label: <Link to="/">{isQa ? 'QA overview' : 'Command center'}</Link> },
      { key: '/queue', icon: <AuditOutlined />, label: <Link to="/queue">{isQa ? 'My reports' : user?.role === 'team_leader' ? 'QA inbox' : 'QA reports'}</Link> },
      { key: '/calls', icon: <CustomerServiceOutlined />, label: <Link to="/calls">{isQa ? 'Calls for review' : 'Call library'}</Link> },
      { key: '/insights', icon: <BarChartOutlined />, label: <Link to="/insights">Quality insights</Link>, roles: ['supervisor', 'administrator'] },
      { key: '/admin', icon: <SettingOutlined />, label: <Link to="/admin">Administration</Link>, roles: ['administrator'] },
      { key: '/account', icon: <UserOutlined />, label: <Link to="/account">Account</Link> },
    ];
    return all.filter((item) => !item.roles || item.roles.includes(user?.role ?? ''));
  }, [isQa, user?.role]);

  const accountMenu: MenuProps['items'] = [
    { key: 'profile', label: 'My account', icon: <UserOutlined />, onClick: () => navigate('/account') },
    { type: 'divider' },
    { key: 'logout', label: 'Sign out', icon: <LogoutOutlined />, danger: true, onClick: async () => { await logout(); navigate('/login'); } },
  ];
  const initials = `${user?.first_name?.[0] ?? ''}${user?.last_name?.[0] ?? ''}`.toUpperCase() || 'U';
  const notificationPanel = (
    <div className="notification-panel">
      <div className="notification-panel__header">
        <span><strong>Notifications</strong><small>{unreadCount ? `${unreadCount} need attention` : 'You are all caught up'}</small></span>
        {unreadCount > 0 && <Button type="link" size="small" icon={<CheckOutlined />} onClick={() => void markAllRead()}>Read all</Button>}
      </div>
      <div className={`notification-panel__list${notificationsLoading ? ' notification-panel__list--loading' : ''}`}>
        {notifications.length ? notifications.map((item) => (
          <button key={item.id} type="button" className={`notification-item${item.is_read ? '' : ' notification-item--unread'}`} onClick={() => { void markRead(item); setNotificationsOpen(false); navigate(item.metadata.target_path || (user?.is_superuser ? '/admin' : '/queue')); }}>
            <span className={`notification-item__indicator notification-item__indicator--${item.severity}`} />
            <span className="notification-item__copy"><strong>{item.title}</strong><span>{item.message}</span><small>{item.occurrences > 1 ? `${item.occurrences} calls · ` : ''}{appDate(item.updated_at).format('DD MMM, h:mm A')} ET</small></span>
          </button>
        )) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No active notifications" />}
      </div>
      {browserPermission === 'default' && <div className="notification-panel__permission"><span><strong>Desktop alerts are off</strong><small>Enable them to receive updates while working in another tab.</small></span><Button size="small" type="primary" onClick={() => void enableBrowserNotifications()}>Enable</Button></div>}
    </div>
  );

  return (
    <Layout className="app-layout" hasSider>
      <Sider width={264} collapsedWidth={76} collapsed={collapsed} trigger={null} breakpoint="lg" onBreakpoint={setCollapsed} className="app-sider" theme="light">
        <div className={`sider-brand${collapsed ? ' sider-brand--collapsed' : ''}`}><BrandMark compact={collapsed} /></div>
        <div className={`sider-nav-header${collapsed ? ' sider-nav-header--collapsed' : ''}`}>
          {!collapsed && <Text className="nav-label">{isQa ? 'QA WORKSPACE' : 'WORKSPACE'}</Text>}
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
            <div className="workspace-card"><span className="workspace-card__icon"><AppstoreOutlined /></span><span><small>{isQa ? 'Assigned branch' : 'Active branch'}</small><strong>{user?.branch?.name ?? 'System-wide'}</strong></span></div>
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
            {!isQa && <Tag color={connection === 'live' ? 'success' : connection === 'offline' ? 'error' : 'default'} className="live-status"><span className={`live-dot ${connection === 'live' ? '' : 'live-dot--muted'}`} />{connection === 'live' ? 'Live' : connection === 'offline' ? 'Offline' : 'Connecting'}</Tag>}
            <Popover content={notificationPanel} trigger="click" placement="bottomRight" open={notificationsOpen} onOpenChange={(open) => { setNotificationsOpen(open); if (open) void loadNotifications(); }} styles={{ content: { padding: 0 } }}><Badge count={unreadCount} size="small" overflowCount={99}><Button type="text" shape="circle" className="header-icon-button" icon={<BellOutlined />} aria-label={`${unreadCount} unread notifications`} /></Badge></Popover>
            <ThemeControls />
            <Dropdown menu={{ items: accountMenu }} trigger={['click']} placement="bottomRight">
              <button className="account-button" type="button">
                <Avatar size={38} className="account-avatar" src={user?.profile_picture_url ?? undefined}>{initials}</Avatar>
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
