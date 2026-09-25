import { ApartmentOutlined, BankOutlined, BgColorsOutlined, CheckCircleFilled, CheckOutlined, DeleteOutlined, DesktopOutlined, MailOutlined, MessageOutlined, MoonOutlined, PaperClipOutlined, PictureOutlined, ProjectOutlined, SafetyCertificateOutlined, SaveOutlined, SendOutlined, SunOutlined, TeamOutlined, UploadOutlined, UserOutlined } from '@ant-design/icons';
import { App as AntApp, Avatar, Button, Card, Divider, Empty, Form, Input, Popconfirm, Segmented, Space, Spin, Switch, Tabs, Tag, Typography, Upload, type UploadFile, type UploadProps } from 'antd';
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { MaterialSymbol } from '../components/MaterialSymbol';
import { TeamAvatarPicker } from '../components/TeamAvatarPicker';
import { api } from '../lib/api';
import { DEFAULT_THEME, THEME_PRESETS, useThemeSettings, type ThemeMode, type ThemePreferences } from '../theme/ThemeContext';
import type { CurrentUser, LedTeam } from '../types';

const { Text, Title } = Typography;
const VALID_TABS = new Set(['profile', 'team', 'appearance', 'feedback']);

function initialsFor(user: CurrentUser | null) {
  return `${user?.first_name?.[0] ?? ''}${user?.last_name?.[0] ?? ''}`.toUpperCase() || 'U';
}

export function AccountPage() {
  const { message } = AntApp.useApp();
  const { user, refresh } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get('tab') ?? 'profile';
  const activeTab = VALID_TABS.has(requestedTab) && (requestedTab !== 'team' || user?.role === 'team_leader') ? requestedTab : 'profile';
  const [uploading, setUploading] = useState(false);
  const [removing, setRemoving] = useState(false);

  const uploadAvatar: UploadProps['customRequest'] = async ({ file, onError, onSuccess }) => {
    const avatar = file as File;
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(avatar.type)) {
      message.error('Choose a JPEG, PNG, or WebP image.');
      onError?.(new Error('Unsupported image type'));
      return;
    }
    if (avatar.size > 5 * 1024 * 1024) {
      message.error('Profile pictures must be 5 MB or smaller.');
      onError?.(new Error('Image is too large'));
      return;
    }
    setUploading(true);
    try {
      const form = new FormData();
      form.append('avatar', avatar);
      await api<CurrentUser>('/api/v1/auth/account/avatar/', { method: 'POST', body: form });
      await refresh();
      onSuccess?.({});
      message.success('Profile picture updated.');
    } catch (error) {
      const reason = error instanceof Error ? error : new Error('Upload failed');
      onError?.(reason);
      message.error(reason.message);
    } finally {
      setUploading(false);
    }
  };

  const removeAvatar = async () => {
    setRemoving(true);
    try {
      await api('/api/v1/auth/account/avatar/', { method: 'DELETE' });
      await refresh();
      message.success('Profile picture removed.');
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Could not remove the picture.');
    } finally {
      setRemoving(false);
    }
  };

  const profile = <div className="account-profile-grid">
    <Card className="account-photo-card" variant="borderless">
      <div className="account-photo-card__halo"><Avatar size={112} src={user?.profile_picture_url ?? undefined} className="account-photo-card__avatar">{initialsFor(user)}</Avatar></div>
      <Title level={4}>{user?.name}</Title><Text type="secondary">{user?.role_label}</Text>
      <Space wrap className="account-photo-card__actions">
        <Upload accept="image/jpeg,image/png,image/webp" maxCount={1} showUploadList={false} customRequest={uploadAvatar} disabled={uploading}><Button type="primary" icon={<UploadOutlined />} loading={uploading}>Change photo</Button></Upload>
        {user?.profile_picture_url && <Popconfirm title="Remove profile picture?" description="Your initials will be shown instead." onConfirm={() => void removeAvatar()}><Button icon={<DeleteOutlined />} loading={removing}>Remove</Button></Popconfirm>}
      </Space>
      <Text type="secondary" className="account-photo-card__hint">JPEG, PNG or WebP · Max 5 MB</Text>
    </Card>
    <Card title="Account information" className="account-detail-card" extra={<Tag color="blue">Read only</Tag>}>
      <Form layout="vertical" requiredMark={false} className="account-readonly-form" aria-label="Account information">
        <div className="account-readonly-grid">
          <Form.Item label="Full name" className="account-readonly-field">
            <Input size="large" variant="filled" readOnly value={user?.name ?? ''} prefix={<UserOutlined />} />
          </Form.Item>
          <Form.Item label="Work email" className="account-readonly-field">
            <Input size="large" variant="filled" readOnly value={user?.email ?? ''} prefix={<MailOutlined />} />
          </Form.Item>
          <Form.Item label="Portal role" className="account-readonly-field">
            <Input size="large" variant="filled" readOnly value={user?.role_label ?? ''} prefix={<SafetyCertificateOutlined />} />
          </Form.Item>
          <Form.Item label="Account status" className="account-readonly-field account-readonly-field--status">
            <Input size="large" variant="filled" readOnly value="Active" prefix={<CheckCircleFilled />} />
          </Form.Item>
          <Form.Item label="Company" className="account-readonly-field">
            <Input size="large" variant="filled" readOnly value={user?.company?.name ?? 'System-wide'} prefix={<BankOutlined />} />
          </Form.Item>
          <Form.Item label="Branch" className="account-readonly-field">
            <Input size="large" variant="filled" readOnly value={user?.branch?.name ?? 'All organizations'} prefix={<ApartmentOutlined />} />
          </Form.Item>
          <Form.Item label="Assigned projects" className="account-readonly-field account-readonly-field--wide">
            <div className="account-readonly-projects" role="group" aria-label="Assigned projects">
              <ProjectOutlined />
              <Space wrap size={[6, 6]}>
                {user?.assigned_projects.length ? user.assigned_projects.map((project) => <Tag key={project.id} color="blue">{project.name}</Tag>) : <Text type="secondary">No project-specific assignment</Text>}
              </Space>
            </div>
          </Form.Item>
        </div>
      </Form>
    </Card>
  </div>;

  const tabs = [
    { key: 'profile', label: 'Profile', icon: <UserOutlined />, children: profile },
    ...(user?.role === 'team_leader' ? [{ key: 'team', label: 'Team avatar', icon: <TeamOutlined />, children: <TeamAvatarSection /> }] : []),
    { key: 'appearance', label: 'Appearance', icon: <BgColorsOutlined />, children: <AppearanceSection /> },
    { key: 'feedback', label: 'Feedback', icon: <MessageOutlined />, children: <FeedbackSection /> },
  ];

  return <div className="account-page">
    <div className="page-heading"><Title level={2} className="page-title">Account</Title></div>
    <Card className="account-shell-card" classNames={{ body: 'account-shell-card__body' }} variant="borderless"><Tabs activeKey={activeTab} animated={{ inkBar: true, tabPane: true }} items={tabs} onChange={(tab) => setSearchParams(tab === 'profile' ? {} : { tab })} /></Card>
  </div>;
}

function TeamAvatarSection() {
  const { message } = AntApp.useApp();
  const [teams, setTeams] = useState<LedTeam[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const load = useCallback(async () => {
    setLoading(true);
    try { setTeams(await api<LedTeam[]>('/api/v1/auth/account/teams/')); }
    catch (error) { message.error(error instanceof Error ? error.message : 'Could not load your teams.'); }
    finally { setLoading(false); }
  }, [message]);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const updateAvatar = async (team: LedTeam, avatar: string) => {
    const previous = team.avatar;
    setTeams((current) => current.map((item) => item.id === team.id ? { ...item, avatar } : item));
    setSaving(team.id);
    try {
      const updated = await api<LedTeam>(`/api/v1/auth/account/teams/${team.id}/avatar/`, { method: 'PATCH', body: JSON.stringify({ avatar }) });
      setTeams((current) => current.map((item) => item.id === team.id ? updated : item));
      message.success(`${team.name} avatar updated.`);
    } catch (error) {
      setTeams((current) => current.map((item) => item.id === team.id ? { ...item, avatar: previous } : item));
      message.error(error instanceof Error ? error.message : 'Could not update the team avatar.');
    } finally { setSaving(null); }
  };

  if (loading) return <div className="account-section-loading"><Spin /><Text type="secondary">Loading team settings…</Text></div>;
  if (!teams.length) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No teams are assigned to you" />;
  return <div className="account-section"><div className="account-section__intro"><Title level={4}>Team identity</Title></div><div className="team-settings-grid">{teams.map((team) => <Card key={team.id} className="team-setting-card" classNames={{ body: 'team-setting-card__body' }}><div className="team-setting-card__identity"><span className="team-avatar team-avatar--account"><MaterialSymbol name={team.avatar} /></span><span><strong>{team.name}</strong><small>{team.is_active ? 'Active team' : 'Inactive team'}</small></span></div><Spin spinning={saving === team.id} size="small"><TeamAvatarPicker value={team.avatar} onChange={(avatar) => void updateAvatar(team, avatar)} /></Spin></Card>)}</div></div>;
}

function AppearanceSection() {
  const { message } = AntApp.useApp();
  const { mode, preset, compact, setMode, setPreset, setCompact, setPreferences } = useThemeSettings();
  const [saved, setSaved] = useState<ThemePreferences>({ mode, preset, compact });
  const [saving, setSaving] = useState(false);
  const preferences = useMemo(() => ({ mode, preset, compact }), [mode, preset, compact]);
  const dirty = saved.mode !== mode || saved.preset !== preset || saved.compact !== compact;
  const save = async () => {
    setSaving(true);
    try {
      const updated = await api<CurrentUser>('/api/v1/auth/account/appearance/', { method: 'PATCH', body: JSON.stringify(preferences) });
      setSaved(updated.appearance); setPreferences(updated.appearance); message.success('Appearance saved.');
    } catch (error) { message.error(error instanceof Error ? error.message : 'Could not save appearance.'); }
    finally { setSaving(false); }
  };

  return <div className="account-section appearance-section">
    <div className="account-section__intro"><Title level={4}>Appearance</Title></div>
    <div className="appearance-setting-row"><div><Text strong>Color mode</Text></div><Segmented<ThemeMode> value={mode} onChange={setMode} options={[{ value: 'light', label: 'Light', icon: <SunOutlined /> }, { value: 'dark', label: 'Dark', icon: <MoonOutlined /> }, { value: 'system', label: 'System', icon: <DesktopOutlined /> }]} /></div>
    <Divider />
    <div className="theme-gallery-heading"><div><Text strong>Theme</Text></div><PictureOutlined className="theme-gallery-heading__icon" /></div>
    <div className="theme-gallery" role="radiogroup" aria-label="Workspace theme">{THEME_PRESETS.map((item) => <button key={item.id} type="button" role="radio" aria-checked={preset === item.id} aria-label={item.name} className={`theme-orb-option${preset === item.id ? ' theme-orb-option--selected' : ''}`} onClick={() => setPreset(item.id)} style={{ '--theme-primary': item.primary, '--theme-secondary': item.secondary } as CSSProperties}><span className="theme-orb"><span className="theme-orb__lens" />{preset === item.id && <CheckOutlined className="theme-orb__check" />}</span><span><strong>{item.name}</strong></span></button>)}</div>
    <Divider />
    <div className="appearance-setting-row"><div><Text strong>Compact density</Text></div><Switch checked={compact} onChange={setCompact} aria-label="Use compact interface density" /></div>
    <div className="appearance-footer"><div /><Space><Button onClick={() => setPreferences(DEFAULT_THEME)}>Reset</Button><Button type="primary" icon={<SaveOutlined />} disabled={!dirty} loading={saving} onClick={() => void save()}>Save appearance</Button></Space></div>
  </div>;
}


function FeedbackSection() {
  const { message } = AntApp.useApp();
  const [form] = Form.useForm<{ message: string }>();
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [submitting, setSubmitting] = useState(false);

  const beforeUpload: UploadProps['beforeUpload'] = (file) => {
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      message.error('Attach JPEG, PNG, or WebP images only.');
      return Upload.LIST_IGNORE;
    }
    if (file.size > 3 * 1024 * 1024) {
      message.error('Each feedback image must be 3 MB or smaller.');
      return Upload.LIST_IGNORE;
    }
    return false;
  };

  const submit = async (values: { message: string }) => {
    setSubmitting(true);
    try {
      const body = new FormData();
      body.append('message', values.message.trim());
      files.forEach((file) => {
        if (file.originFileObj) body.append('images', file.originFileObj);
      });
      await api('/api/v1/feedback/', { method: 'POST', body });
      form.resetFields();
      setFiles([]);
      message.success('Feedback sent to the System Administrator.');
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Feedback could not be sent.');
    } finally {
      setSubmitting(false);
    }
  };

  return <div className="account-section feedback-section">
    <div className="account-section__intro"><Title level={4}>Feedback</Title></div>
    <Card className="feedback-compose-card" variant="borderless">
      <Form form={form} layout="vertical" requiredMark={false} onFinish={submit}>
        <Form.Item name="message" label="What would you like us to know?" rules={[{ required: true, whitespace: true, message: 'Enter your feedback.' }, { max: 3000 }]}>
          <Input.TextArea autoSize={{ minRows: 5, maxRows: 10 }} maxLength={3000} showCount placeholder="Describe the issue, suggestion, or improvement." />
        </Form.Item>
        <Form.Item label="Screenshots" extra="Optional · Up to 3 JPEG, PNG, or WebP images · 3 MB each">
          <Upload
            accept="image/jpeg,image/png,image/webp"
            multiple
            maxCount={3}
            beforeUpload={beforeUpload}
            fileList={files}
            listType="picture"
            onChange={({ fileList }) => setFiles(fileList.slice(-3))}
          >
            <Button icon={<PaperClipOutlined />} disabled={files.length >= 3}>Attach images</Button>
          </Upload>
        </Form.Item>
        <div className="feedback-compose-actions"><Button type="primary" htmlType="submit" icon={<SendOutlined />} loading={submitting}>Send feedback</Button></div>
      </Form>
    </Card>
  </div>;
}
