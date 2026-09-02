import { ArrowRightOutlined, CheckCircleFilled, LockOutlined, MailOutlined, SafetyCertificateFilled } from '@ant-design/icons';
import { Alert, Button, Checkbox, Form, Input, Typography } from 'antd';
import { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { BrandMark } from '../components/BrandMark';
import { ThemeControls } from '../components/ThemeControls';
import { ApiError } from '../lib/api';

const { Title, Paragraph, Text } = Typography;

interface LoginValues {
  email: string;
  password: string;
  remember: boolean;
}

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const submit = async (values: LoginValues) => {
    setError('');
    setSubmitting(true);
    try {
      await login(values.email, values.password, values.remember ?? false);
      const destination = (location.state as { from?: string } | null)?.from ?? '/';
      navigate(destination, { replace: true });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'We could not sign you in. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="auth-layout">
      <section className="auth-story" aria-label="Product overview">
        <div className="auth-story__glow auth-story__glow--one" />
        <div className="auth-story__glow auth-story__glow--two" />
        <BrandMark />
        <div className="auth-story__content">
          <Text className="eyebrow">QUALITY, IN FOCUS</Text>
          <Title level={1}>Every conversation.<br />One clear standard.</Title>
          <Paragraph>
            Turn live dialer activity into consistent reviews, focused coaching, and measurable operational confidence.
          </Paragraph>
          <div className="auth-benefits">
            <div><CheckCircleFilled /><span><strong>Real-time intake</strong><small>Calls and recordings organized automatically</small></span></div>
            <div><CheckCircleFilled /><span><strong>Branch-level control</strong><small>The right work, visible to the right team</small></span></div>
            <div><CheckCircleFilled /><span><strong>Actionable quality</strong><small>From review queue to coaching insight</small></span></div>
          </div>
        </div>
        <div className="auth-story__footer">
          <span className="live-dot" /> Secure operations workspace
          <span>Built for focused teams</span>
        </div>
      </section>

      <section className="auth-panel">
        <ThemeControls className="auth-theme-controls" />
        <div className="auth-panel__inner">
          <div className="auth-panel__mobile-brand"><BrandMark /></div>
          <div className="auth-heading">
            <div className="auth-heading__icon"><SafetyCertificateFilled /></div>
            <Title level={2}>Welcome back</Title>
            <Paragraph>Sign in to continue to your quality workspace.</Paragraph>
          </div>

          {error && <Alert type="error" showIcon title="Sign-in unsuccessful" description={error} closable={{ onClose: () => setError('') }} />}

          <Form<LoginValues> layout="vertical" size="large" requiredMark={false} onFinish={submit} initialValues={{ remember: false }} className="login-form">
            <Form.Item label="Work email" name="email" rules={[{ required: true, message: 'Enter your work email' }, { type: 'email', message: 'Enter a valid email address' }]}>
              <Input prefix={<MailOutlined />} placeholder="you@company.com" autoComplete="username" autoFocus />
            </Form.Item>
            <Form.Item label="Password" name="password" rules={[{ required: true, message: 'Enter your password' }]}>
              <Input.Password prefix={<LockOutlined />} placeholder="Enter your password" autoComplete="current-password" />
            </Form.Item>
            <div className="login-form__options">
              <Form.Item name="remember" valuePropName="checked" noStyle><Checkbox>Keep me signed in</Checkbox></Form.Item>
              <Link to="/forgot-password">Forgot password?</Link>
            </div>
            <Button type="primary" htmlType="submit" block loading={submitting} icon={<ArrowRightOutlined />} iconPlacement="end">
              Sign in securely
            </Button>
          </Form>

          <div className="auth-security-note">
            <LockOutlined />
            <Text type="secondary">Protected with encrypted sessions and access controls.</Text>
          </div>
          <Text className="support-note" type="secondary">Need access? Contact your system administrator.</Text>
        </div>
      </section>
    </main>
  );
}
