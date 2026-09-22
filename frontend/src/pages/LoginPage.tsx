import { LockOutlined, MailOutlined } from '@ant-design/icons';
import { Alert, Button, Checkbox, Form, Input, Typography } from 'antd';
import { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { BrandMark } from '../components/BrandMark';
import { ThemeControls } from '../components/ThemeControls';
import { ApiError } from '../lib/api';

const { Title } = Typography;

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
    <main className="login-page">
      <ThemeControls className="auth-theme-controls" />
      <section className="login-card" aria-label="Sign in">
        <div className="login-brand"><BrandMark /></div>
        <Title level={2} className="auth-form-title">Sign in</Title>

        {error && (
          <Alert
            className="auth-alert"
            type="error"
            showIcon
            title="Sign-in unsuccessful"
            description={error}
            closable={{ onClose: () => setError('') }}
          />
        )}

        <Form<LoginValues>
          layout="vertical"
          size="large"
          requiredMark={false}
          onFinish={submit}
          initialValues={{ remember: false }}
          className="login-form"
          classNames={{ label: 'login-form__label' }}
        >
          <Form.Item
            label="Work email"
            name="email"
            rules={[
              { required: true, message: 'Enter your work email' },
              { type: 'email', message: 'Enter a valid email address' },
            ]}
          >
            <Input
              className="login-input"
              prefix={<MailOutlined />}
              placeholder="you@company.com"
              autoComplete="username"
              autoFocus
            />
          </Form.Item>

          <Form.Item
            label="Password"
            name="password"
            rules={[{ required: true, message: 'Enter your password' }]}
          >
            <Input.Password
              className="login-input"
              prefix={<LockOutlined />}
              placeholder="Password"
              autoComplete="current-password"
            />
          </Form.Item>

          <div className="login-form__options">
            <Form.Item name="remember" valuePropName="checked" noStyle>
              <Checkbox className="login-checkbox">Keep me signed in</Checkbox>
            </Form.Item>
            <Link to="/forgot-password">Forgot password?</Link>
          </div>

          <Button type="primary" htmlType="submit" block loading={submitting}>
            Sign in
          </Button>
        </Form>
      </section>
    </main>
  );
}
