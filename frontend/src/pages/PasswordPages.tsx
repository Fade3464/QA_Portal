import { ArrowLeftOutlined, LockOutlined, MailOutlined } from '@ant-design/icons';
import { Alert, Button, Form, Input, Result, Typography } from 'antd';
import { useState } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { BrandMark } from '../components/BrandMark';
import { ThemeControls } from '../components/ThemeControls';
import { api, ApiError } from '../lib/api';

const { Title, Paragraph } = Typography;

function AuthCard({ children }: { children: React.ReactNode }) {
  return <main className="simple-auth"><ThemeControls className="simple-auth__theme" /><div className="simple-auth__card"><BrandMark />{children}</div></main>;
}

export function ForgotPasswordPage() {
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  if (sent) return <AuthCard><Result status="success" title="Check your inbox" subTitle="If an account matches that email, a secure reset link is on its way." extra={<Button type="primary" href="/login">Return to sign in</Button>} /></AuthCard>;
  return <AuthCard>
    <div className="simple-auth__heading"><Title level={2} className="auth-form-title">Reset your password</Title><Paragraph className="auth-form-copy">Enter your work email and we’ll send a time-limited reset link.</Paragraph></div>
    {error && <Alert className="auth-alert" type="error" title={error} showIcon />}
    <Form layout="vertical" size="large" requiredMark={false} onFinish={async ({ email }) => { setLoading(true); setError(''); try { await api('/api/v1/auth/password-reset/', { method: 'POST', body: JSON.stringify({ email }) }); setSent(true); } catch (caught) { setError(caught instanceof ApiError ? caught.message : 'Please try again.'); } finally { setLoading(false); } }}>
      <Form.Item label="Work email" name="email" rules={[{ required: true }, { type: 'email' }]}><Input prefix={<MailOutlined />} autoComplete="email" placeholder="you@company.com" /></Form.Item>
      <Button type="primary" htmlType="submit" loading={loading} block>Send reset link</Button>
    </Form>
    <Link className="back-link" to="/login"><ArrowLeftOutlined /> Back to sign in</Link>
  </AuthCard>;
}

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const [complete, setComplete] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  if (complete) return <AuthCard><Result status="success" title="Password updated" subTitle="Your new password is ready to use." extra={<Button type="primary" href="/login">Sign in</Button>} /></AuthCard>;
  return <AuthCard>
    <div className="simple-auth__heading"><Title level={2} className="auth-form-title">Choose a new password</Title><Paragraph className="auth-form-copy">Use at least 12 characters and avoid common phrases.</Paragraph></div>
    {error && <Alert className="auth-alert" type="error" title={error} showIcon />}
    <Form layout="vertical" size="large" requiredMark={false} onFinish={async ({ password }) => { setLoading(true); setError(''); try { await api('/api/v1/auth/password-reset/confirm/', { method: 'POST', body: JSON.stringify({ uid: params.get('uid'), token: params.get('token'), password }) }); setComplete(true); } catch (caught) { setError(caught instanceof ApiError ? caught.message : 'Please try again.'); } finally { setLoading(false); } }}>
      <Form.Item label="New password" name="password" rules={[{ required: true }, { min: 12, message: 'Use at least 12 characters' }]}><Input.Password prefix={<LockOutlined />} autoComplete="new-password" /></Form.Item>
      <Form.Item label="Confirm password" name="confirm" dependencies={['password']} rules={[{ required: true }, ({ getFieldValue }) => ({ validator(_, value) { return !value || getFieldValue('password') === value ? Promise.resolve() : Promise.reject(new Error('Passwords do not match')); } })]}><Input.Password prefix={<LockOutlined />} autoComplete="new-password" /></Form.Item>
      <Button type="primary" htmlType="submit" loading={loading} block>Update password</Button>
    </Form>
  </AuthCard>;
}

export function ChangePasswordPage() {
  const { user, loading: authLoading, changePassword, logout } = useAuth();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  if (authLoading) return <main className="simple-auth" />;
  if (!user) return <Navigate to="/login" replace />;
  if (!user.must_change_password) return <Navigate to="/" replace />;
  return <AuthCard>
    <div className="simple-auth__heading"><Title level={2} className="auth-form-title">Secure your account</Title><Paragraph className="auth-form-copy">Replace the temporary password before entering your workspace.</Paragraph></div>
    {error && <Alert className="auth-alert" type="error" title={error} showIcon />}
    <Form layout="vertical" size="large" requiredMark={false} onFinish={async ({ currentPassword, password }) => { setLoading(true); setError(''); try { await changePassword(currentPassword, password); navigate('/', { replace: true }); } catch (caught) { setError(caught instanceof ApiError ? caught.message : 'Please try again.'); } finally { setLoading(false); } }}>
      <Form.Item label="Temporary password" name="currentPassword" rules={[{ required: true }]}><Input.Password prefix={<LockOutlined />} autoComplete="current-password" /></Form.Item>
      <Form.Item label="New password" name="password" rules={[{ required: true }, { min: 12, message: 'Use at least 12 characters' }]}><Input.Password prefix={<LockOutlined />} autoComplete="new-password" /></Form.Item>
      <Form.Item label="Confirm new password" name="confirm" dependencies={['password']} rules={[{ required: true }, ({ getFieldValue }) => ({ validator(_, value) { return !value || getFieldValue('password') === value ? Promise.resolve() : Promise.reject(new Error('Passwords do not match')); } })]}><Input.Password prefix={<LockOutlined />} autoComplete="new-password" /></Form.Item>
      <Button type="primary" htmlType="submit" loading={loading} block>Save and continue</Button>
    </Form>
    <Button type="link" className="signout-link" onClick={async () => { await logout(); navigate('/login'); }}>Sign in with another account</Button>
  </AuthCard>;
}
