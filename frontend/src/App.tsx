import { App as AntApp, ConfigProvider, theme } from 'antd';
import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useAuth } from './auth/AuthContext';
import { AppShell } from './components/AppShell';
import { AppErrorBoundary } from './components/AppErrorBoundary';
import { ContentLoader } from './components/LoadingStates';
import { useThemeSettings } from './theme/ThemeContext';

const CallsPage = lazy(() => import('./pages/CallsPage').then((module) => ({ default: module.CallsPage })));
const DashboardPage = lazy(() => import('./pages/DashboardPage').then((module) => ({ default: module.DashboardPage })));
const LoginPage = lazy(() => import('./pages/LoginPage').then((module) => ({ default: module.LoginPage })));
const ForgotPasswordPage = lazy(() => import('./pages/PasswordPages').then((module) => ({ default: module.ForgotPasswordPage })));
const ResetPasswordPage = lazy(() => import('./pages/PasswordPages').then((module) => ({ default: module.ResetPasswordPage })));
const ChangePasswordPage = lazy(() => import('./pages/PasswordPages').then((module) => ({ default: module.ChangePasswordPage })));
const PlaceholderPage = lazy(() => import('./pages/PlaceholderPage').then((module) => ({ default: module.PlaceholderPage })));
const AdministrationPage = lazy(() => import('./pages/AdministrationPage').then((module) => ({ default: module.AdministrationPage })));
const ReportsPage = lazy(() => import('./pages/ReportsPage').then((module) => ({ default: module.ReportsPage })));
const ProjectPerformancePage = lazy(() => import('./pages/ProjectPerformancePage').then((module) => ({ default: module.ProjectPerformancePage })));
const AccountPage = lazy(() => import('./pages/AccountPage').then((module) => ({ default: module.AccountPage })));

function ProtectedLayout() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <ContentLoader fullPage label="Preparing your workspace" />;
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  if (user.must_change_password) return <Navigate to="/change-password" replace />;
  return <AppShell />;
}

function AdministratorRoute() {
  const { user } = useAuth();
  return user?.is_superuser ? <AdministrationPage /> : <Navigate to="/" replace />;
}

function TeamPerformanceRoute() {
  const { user } = useAuth();
  if (user?.role === 'project_manager') return <ProjectPerformancePage />;
  return user && ['supervisor', 'administrator'].includes(user.role) ? <PlaceholderPage /> : <Navigate to="/" replace />;
}

function ManagementRoute() {
  const { user } = useAuth();
  return user && ['supervisor', 'administrator'].includes(user.role) ? <PlaceholderPage /> : <Navigate to="/" replace />;
}

export default function App() {
  const { resolvedMode, primaryColor, borderRadius, compact } = useThemeSettings();
  const dark = resolvedMode === 'dark';
  const surface = dark ? '#161a23' : '#ffffff';
  const text = dark ? '#edf1f7' : '#172033';
  const muted = dark ? '#a2aaba' : '#70798d';
  const soft = dark ? '#1b202b' : '#f4f7fb';

  return (
    <ConfigProvider
      theme={{
        algorithm: [dark ? theme.darkAlgorithm : theme.defaultAlgorithm, ...(compact ? [theme.compactAlgorithm] : [])],
        token: {
          colorPrimary: primaryColor,
          colorInfo: primaryColor,
          colorSuccess: '#16a67a',
          colorWarning: '#e6a23c',
          colorError: '#e05260',
          colorTextBase: dark ? '#edf1f7' : '#172033',
          colorBgBase: dark ? '#10131a' : '#f5f7fb',
          borderRadius: Math.min(borderRadius, 8),
          borderRadiusLG: 8,
          fontFamily: "'DM Sans', ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
          controlHeight: 40,
        },
        components: {
          Button: { controlHeightLG: 48, fontWeight: 650, primaryShadow: 'none' },
          Card: { headerFontSize: 15, headerBg: surface },
          Input: { controlHeightLG: 48, activeShadow: `0 0 0 3px ${primaryColor}1f` },
          Layout: { bodyBg: dark ? '#10131a' : '#f5f7fb', headerBg: surface, siderBg: surface, lightSiderBg: surface, lightTriggerBg: surface },
          Menu: {
            itemBg: surface,
            subMenuItemBg: surface,
            itemColor: muted,
            itemHoverColor: text,
            itemHoverBg: soft,
            itemSelectedBg: `${primaryColor}18`,
            itemSelectedColor: primaryColor,
            itemBorderRadius: 6,
            itemHeight: 46,
            itemMarginBlock: 4,
            itemMarginInline: 12,
            iconSize: 17,
            collapsedIconSize: 17,
            iconMarginInlineEnd: 12,
          },
          Statistic: { titleFontSize: 12, contentFontSize: 29 },
          Table: {
            headerBg: 'var(--qa-surface-soft)',
            bodySortBg: 'transparent',
            headerSortActiveBg: 'var(--qa-surface-soft)',
            headerSortHoverBg: 'var(--qa-surface-soft)',
            fixedHeaderSortActiveBg: 'var(--qa-surface-soft)',
          },
        },
      }}
    >
      <AntApp>
        <AppErrorBoundary>
          <Suspense fallback={<ContentLoader fullPage label="Loading workspace" />}>
            <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />
            <Route path="/change-password" element={<ChangePasswordPage />} />
            <Route element={<ProtectedLayout />}>
              <Route index element={<DashboardPage />} />
              <Route path="calls" element={<CallsPage />} />
              <Route path="queue" element={<ReportsPage />} />
              <Route path="team" element={<TeamPerformanceRoute />} />
              <Route path="insights" element={<ManagementRoute />} />
              <Route path="admin" element={<AdministratorRoute />} />
              <Route path="administration" element={<AdministratorRoute />} />
              <Route path="account" element={<AccountPage />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </AppErrorBoundary>
      </AntApp>
    </ConfigProvider>
  );
}
