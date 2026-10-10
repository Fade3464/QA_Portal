import { App as AntApp, ConfigProvider } from 'antd';
import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useAuth } from './auth/AuthContext';
import { AppShell } from './components/AppShell';
import { AppErrorBoundary } from './components/AppErrorBoundary';
import { ContentLoader } from './components/LoadingStates';
import { useThemeSettings } from './theme/ThemeContext';
import { canUseAI } from './lib/ai';

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
const AIInsightsPage = lazy(() => import('./pages/AIInsightsPage').then((module) => ({ default: module.AIInsightsPage })));

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
  if (user?.role === 'project_manager' || user?.role === 'supervisor') return <ProjectPerformancePage />;
  return user?.role === 'administrator' ? <PlaceholderPage /> : <Navigate to="/" replace />;
}

function AIInsightsRoute() {
  const { user } = useAuth();
  return canUseAI(user) ? <AIInsightsPage /> : <Navigate to="/" replace />;
}

function ManagementRoute() {
  const { user } = useAuth();
  return user?.role === 'administrator' ? <PlaceholderPage /> : <Navigate to="/" replace />;
}

export default function App() {
  const { providerProps } = useThemeSettings();

  return (
    <ConfigProvider {...providerProps}>
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
              <Route path="ai" element={<AIInsightsRoute />} />
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
