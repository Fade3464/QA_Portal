import {
  ApartmentOutlined,
  ApiOutlined,
  BankOutlined,
  CheckCircleFilled,
  ClusterOutlined,
  CopyOutlined,
  EditOutlined,
  KeyOutlined,
  MinusCircleOutlined,
  NotificationOutlined,
  PlusOutlined,
  ProjectOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SearchOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import {
  App as AntApp,
  Alert,
  Avatar,
  Button,
  Card,
  Col,
  Drawer,
  Form,
  Input,
  Row,
  Select,
  Space,
  Statistic,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  type FormInstance,
  type TableProps,
} from 'antd';
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { AdminNotificationCenter } from '../components/AdminNotificationCenter';
import { api, ApiError } from '../lib/api';
import { appDate } from '../lib/datetime';
import { MaterialSymbol } from '../components/MaterialSymbol';
import { ContentLoader } from '../components/LoadingStates';
import { TeamAvatarPicker } from '../components/TeamAvatarPicker';
import type { AdminSummary, AdminUserRecord, BranchRecord, CompanyRecord, DialerRecord, SecurityEvent, TeamRecord } from '../types';

const { Title, Text } = Typography;
type Resource = 'companies' | 'branches' | 'teams' | 'users' | 'dialers';
type ManagedRecord = CompanyRecord | BranchRecord | TeamRecord | AdminUserRecord | DialerRecord;
type EditorState = { resource: Resource; record?: ManagedRecord; defaults?: Record<string, unknown> } | null;

const resourceLabels: Record<Resource, { singular: string; plural: string }> = {
  companies: { singular: 'company', plural: 'Companies' },
  branches: { singular: 'branch', plural: 'Branches' },
  teams: { singular: 'team', plural: 'Teams' },
  users: { singular: 'user', plural: 'Users' },
  dialers: { singular: 'dialer', plural: 'Dialers' },
};

const roleOptions = [
  { value: 'qa', label: 'QA Analyst' },
  { value: 'team_leader', label: 'Team Leader' },
  { value: 'project_manager', label: 'Project Manager' },
  { value: 'supervisor', label: 'Supervisor' },
];

export function AdministrationPage() {
  const { message } = AntApp.useApp();
  const [summary, setSummary] = useState<AdminSummary | null>(null);
  const [companies, setCompanies] = useState<CompanyRecord[]>([]);
  const [branches, setBranches] = useState<BranchRecord[]>([]);
  const [teams, setTeams] = useState<TeamRecord[]>([]);
  const [users, setUsers] = useState<AdminUserRecord[]>([]);
  const [dialers, setDialers] = useState<DialerRecord[]>([]);
  const [securityEvents, setSecurityEvents] = useState<SecurityEvent[]>([]);
  const [activeTab, setActiveTab] = useState('overview');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [saving, setSaving] = useState(false);
  const [projectSaving, setProjectSaving] = useState(false);
  const [editor, setEditor] = useState<EditorState>(null);
  const [projectEditor, setProjectEditor] = useState<AdminUserRecord | null>(null);
  const [form] = Form.useForm();
  const [projectForm] = Form.useForm();
  const selectedCompany = Form.useWatch('company', form) as string | undefined;
  const selectedBranch = Form.useWatch('branch', form) as string | undefined;
  const selectedRole = Form.useWatch('role', form) as AdminUserRecord['role'] | undefined;

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const [nextSummary, nextCompanies, nextBranches, nextTeams, nextUsers, nextDialers, nextEvents] = await Promise.all([
        api<AdminSummary>('/api/v1/administration/summary/'),
        api<CompanyRecord[]>('/api/v1/administration/companies/'),
        api<BranchRecord[]>('/api/v1/administration/branches/'),
        api<TeamRecord[]>('/api/v1/administration/teams/'),
        api<AdminUserRecord[]>('/api/v1/administration/users/'),
        api<DialerRecord[]>('/api/v1/administration/dialers/'),
        api<SecurityEvent[]>('/api/v1/administration/security-events/'),
      ]);
      setSummary(nextSummary);
      setCompanies(nextCompanies);
      setBranches(nextBranches);
      setTeams(nextTeams);
      setUsers(nextUsers);
      setDialers(nextDialers);
      setSecurityEvents(nextEvents);
    } catch (error) {
      const detail = error instanceof ApiError ? error.message : 'Administration data could not be loaded.';
      setLoadError(detail);
      message.error(detail);
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => { void load(); });
    return () => window.cancelAnimationFrame(frame);
  }, [load]);
  useEffect(() => {
    if (!editor) return;
    form.resetFields();
    if (editor.record) {
      const record = editor.record as ManagedRecord & { assigned_projects?: AdminUserRecord['assigned_projects'] };
      form.setFieldsValue({
        ...record,
        project_assignment_ids: record.assigned_projects?.map((project) => project.id) ?? [],
      });
    }
    else form.setFieldsValue({ is_active: true, must_change_password: true, timezone: 'America/New_York', request_timeout_seconds: 15, api_source: 'qa_portal', avatar: 'groups', ...editor.defaults });
  }, [editor, form]);

  const normalizedQuery = query.trim().toLowerCase();
  const filter = useCallback(<T,>(items: T[], fields: (keyof T)[]) => !normalizedQuery ? items : items.filter((item) => fields.some((field) => String(item[field] ?? '').toLowerCase().includes(normalizedQuery))), [normalizedQuery]);

  const openEditor = (resource: Resource, record?: ManagedRecord, defaults?: Record<string, unknown>) => setEditor({ resource, record, defaults });

  const openProjectEditor = (user: AdminUserRecord) => setProjectEditor(user);

  const saveProjectAccess = async (values: { project_assignment_ids?: string[] }) => {
    if (!projectEditor) return;
    setProjectSaving(true);
    try {
      await api(`/api/v1/administration/users/${projectEditor.id}/`, {
        method: 'PATCH',
        body: JSON.stringify({ project_assignment_ids: values.project_assignment_ids ?? [] }),
      });
      message.success(`Project access updated for ${projectEditor.name}.`);
      setProjectEditor(null);
      projectForm.resetFields();
      await load();
    } catch (error) {
      message.error(error instanceof ApiError ? error.message : 'Project access could not be updated.');
    } finally {
      setProjectSaving(false);
    }
  };

  const save = async (values: Record<string, unknown>) => {
    if (!editor) return;
    setSaving(true);
    const payload = { ...values };
    if (!payload.password) delete payload.password;
    if (!payload.api_password) delete payload.api_password;
    if (!payload.webhook_secret) delete payload.webhook_secret;
    try {
      await api(`/api/v1/administration/${editor.resource}/${editor.record?.id ? `${editor.record.id}/` : ''}`, {
        method: editor.record ? 'PATCH' : 'POST',
        body: JSON.stringify(payload),
      });
      message.success(`${resourceLabels[editor.resource].singular[0].toUpperCase()}${resourceLabels[editor.resource].singular.slice(1)} ${editor.record ? 'updated' : 'created'}.`);
      setEditor(null);
      await load();
    } catch (error) {
      message.error(error instanceof ApiError ? error.message : 'The changes could not be saved.');
    } finally {
      setSaving(false);
    }
  };

  const setActive = async (resource: Resource, record: ManagedRecord, isActive: boolean) => {
    try {
      await api(`/api/v1/administration/${resource}/${record.id}/`, { method: 'PATCH', body: JSON.stringify({ is_active: isActive }) });
      message.success(`${resourceLabels[resource].singular[0].toUpperCase()}${resourceLabels[resource].singular.slice(1)} ${isActive ? 'activated' : 'paused'}.`);
      await load();
    } catch (error) {
      message.error(error instanceof ApiError ? error.message : 'Status could not be changed.');
    }
  };

  const companyColumns: TableProps<CompanyRecord>['columns'] = [
    { title: 'Company', key: 'name', render: (_, row) => <EntityCell icon={<BankOutlined />} title={row.name} detail={row.slug} /> },
    { title: 'Branches', dataIndex: 'branches_count', key: 'branches_count', width: 110 },
    { title: 'Users', dataIndex: 'users_count', key: 'users_count', width: 100 },
    { title: 'Status', key: 'status', width: 130, render: (_, row) => <StatusSwitch checked={row.is_active} onChange={(checked) => void setActive('companies', row, checked)} /> },
    { title: '', key: 'actions', width: 64, render: (_, row) => <EditButton onClick={() => openEditor('companies', row)} /> },
  ];
  const branchColumns: TableProps<BranchRecord>['columns'] = [
    { title: 'Branch', key: 'name', render: (_, row) => <EntityCell icon={<ApartmentOutlined />} title={row.name} detail={`${row.company_name} · ${row.code}`} /> },
    { title: 'Timezone', dataIndex: 'timezone', key: 'timezone' },
    { title: 'Users', dataIndex: 'users_count', key: 'users_count', width: 90 },
    { title: 'Dialers', dataIndex: 'dialers_count', key: 'dialers_count', width: 90 },
    { title: 'Status', key: 'status', width: 130, render: (_, row) => <StatusSwitch checked={row.is_active} onChange={(checked) => void setActive('branches', row, checked)} /> },
    { title: '', key: 'actions', width: 64, render: (_, row) => <EditButton onClick={() => openEditor('branches', row)} /> },
  ];
  const userColumns: TableProps<AdminUserRecord>['columns'] = [
    { title: 'User', key: 'user', render: (_, row) => <EntityCell icon={<Avatar size={34}>{`${row.first_name[0] ?? ''}${row.last_name[0] ?? ''}`}</Avatar>} title={row.name} detail={row.email} /> },
    { title: 'Role', dataIndex: 'role_label', key: 'role', render: (value) => <Tag color="blue">{value}</Tag> },
    { title: 'Workspace', key: 'workspace', render: (_, row) => <span><strong>{row.company_name}</strong><br /><Text type="secondary">{row.branch_name}</Text></span> },
    { title: 'Project access', key: 'project_access', width: 180, render: (_, row) => ['qa', 'team_leader', 'project_manager'].includes(row.role) ? <ProjectAccessCell projects={row.assigned_projects} onManage={() => openProjectEditor(row)} /> : <Text type="secondary">Not applicable</Text> },
    { title: 'Last login', dataIndex: 'last_login', key: 'last_login', render: (value) => value ? `${appDate(value).format('DD MMM, h:mm A')} ET` : 'Never' },
    { title: 'Status', key: 'status', width: 130, render: (_, row) => <StatusSwitch checked={row.is_active} onChange={(checked) => void setActive('users', row, checked)} /> },
    { title: '', key: 'actions', width: 64, render: (_, row) => <EditButton onClick={() => openEditor('users', row)} /> },
  ];
  const projectManagerColumns: TableProps<AdminUserRecord>['columns'] = [
    { title: 'Project Manager', key: 'user', render: (_, row) => <EntityCell icon={<Avatar size={34}>{`${row.first_name[0] ?? ''}${row.last_name[0] ?? ''}`}</Avatar>} title={row.name} detail={row.email} /> },
    { title: 'Workspace', key: 'workspace', render: (_, row) => <span><strong>{row.company_name}</strong><br /><Text type="secondary">{row.branch_name}</Text></span> },
    { title: 'Assigned projects', key: 'projects', minWidth: 320, render: (_, row) => <ProjectAccessCell projects={row.assigned_projects} onManage={() => openProjectEditor(row)} /> },
    { title: 'Status', key: 'status', width: 130, render: (_, row) => <StatusSwitch checked={row.is_active} onChange={(checked) => void setActive('users', row, checked)} /> },
    { title: '', key: 'actions', width: 64, render: (_, row) => <EditButton onClick={() => openEditor('users', row)} /> },
  ];
  const teamColumns: TableProps<TeamRecord>['columns'] = [
    { title: 'Team', key: 'team', render: (_, row) => <EntityCell icon={<MaterialSymbol name={row.avatar} />} title={row.name} detail={`${row.company_name} · ${row.branch_name}`} /> },
    { title: 'Team leader', key: 'leader', render: (_, row) => <span><strong>{row.team_leader_name}</strong><br /><Text type="secondary">{row.team_leader_email}</Text></span> },
    { title: 'Leader projects', key: 'leader_projects', width: 260, render: (_, row) => { const leader = users.find((user) => user.id === row.team_leader); return leader ? <ProjectAccessCell projects={leader.assigned_projects} onManage={() => openProjectEditor(leader)} /> : <Text type="secondary">Leader account unavailable</Text>; } },
    { title: 'Calls', dataIndex: 'calls_count', key: 'calls_count', width: 90 },
    { title: 'Status', key: 'status', width: 130, render: (_, row) => <StatusSwitch checked={row.is_active} onChange={(checked) => void setActive('teams', row, checked)} /> },
    { title: '', key: 'actions', width: 64, render: (_, row) => <EditButton onClick={() => openEditor('teams', row)} /> },
  ];
  const dialerColumns: TableProps<DialerRecord>['columns'] = [
    { title: 'Dialer', key: 'dialer', render: (_, row) => <EntityCell icon={<ApiOutlined />} title={row.name} detail={`${row.company_name} · ${row.branch_name}`} /> },
    { title: 'API endpoint', dataIndex: 'api_url', key: 'api_url', ellipsis: true },
    { title: 'Source', dataIndex: 'api_source', key: 'api_source', render: (value) => <Tag>{value}</Tag> },
    { title: 'Campaigns', key: 'campaigns', width: 120, render: (_, row) => <span><strong>{row.campaigns.length}</strong><br /><Text type="secondary">project mappings</Text></span> },
    { title: 'Webhook', key: 'webhook', width: 110, render: (_, row) => <Tooltip title="Copy webhook path"><Button type="text" icon={<CopyOutlined />} onClick={() => { if (navigator.clipboard) { void navigator.clipboard.writeText(row.webhook_path); message.success('Webhook path copied.'); } else message.info(row.webhook_path); }} /></Tooltip> },
    { title: 'Status', key: 'status', width: 130, render: (_, row) => <StatusSwitch checked={row.is_active} onChange={(checked) => void setActive('dialers', row, checked)} /> },
    { title: '', key: 'actions', width: 64, render: (_, row) => <EditButton onClick={() => openEditor('dialers', row)} /> },
  ];
  const eventColumns: TableProps<SecurityEvent>['columns'] = [
    { title: 'Event', key: 'event', render: (_, row) => <Space><span className={`event-dot event-dot--${row.event.includes('failure') ? 'danger' : 'success'}`} /><strong>{row.event_label}</strong></Space> },
    { title: 'Identity', key: 'identity', render: (_, row) => <span>{row.user_name || 'Unknown user'}<br /><Text type="secondary">{row.email}</Text></span> },
    { title: 'IP address', dataIndex: 'ip_address', key: 'ip_address', render: (value) => value || '—' },
    { title: 'Time', dataIndex: 'created_at', key: 'created_at', render: (value) => `${appDate(value).format('DD MMM YYYY, h:mm A')} ET` },
  ];

  const tabs = [
    { key: 'overview', label: 'Overview', children: <AdministrationOverview summary={summary} events={summary?.recent_security_events ?? []} loading={loading} onNavigate={setActiveTab} /> },
    { key: 'companies', label: <TabLabel label="Companies" count={companies.length} />, children: <ResourceTable resource="companies" query={query} onQuery={setQuery} loading={loading} onAdd={() => openEditor('companies')} columns={companyColumns} data={filter(companies, ['name', 'slug'])} /> },
    { key: 'branches', label: <TabLabel label="Branches" count={branches.length} />, children: <ResourceTable resource="branches" query={query} onQuery={setQuery} loading={loading} onAdd={() => openEditor('branches')} columns={branchColumns} data={filter(branches, ['name', 'code', 'company_name'])} /> },
    { key: 'teams', label: <TabLabel label="Teams" count={teams.length} />, children: <ResourceTable resource="teams" query={query} onQuery={setQuery} loading={loading} onAdd={() => openEditor('teams')} columns={teamColumns} data={filter(teams, ['name', 'team_leader_name', 'team_leader_email', 'company_name', 'branch_name'])} /> },
    { key: 'users', label: <TabLabel label="Users" count={users.length} />, children: <ResourceTable resource="users" query={query} onQuery={setQuery} loading={loading} onAdd={() => openEditor('users')} columns={userColumns} data={filter(users, ['name', 'email', 'role_label', 'company_name', 'branch_name'])} /> },
    { key: 'project-managers', label: <TabLabel label="Project Managers" count={users.filter((user) => user.role === 'project_manager').length} />, children: <ProjectManagerAccessTable query={query} onQuery={setQuery} loading={loading} managers={filter(users.filter((user) => user.role === 'project_manager'), ['name', 'email', 'company_name', 'branch_name'])} columns={projectManagerColumns} onAdd={() => openEditor('users', undefined, { role: 'project_manager' })} /> },
    { key: 'dialers', label: <TabLabel label="Dialers" count={dialers.length} />, children: <ResourceTable resource="dialers" query={query} onQuery={setQuery} loading={loading} onAdd={() => openEditor('dialers')} columns={dialerColumns} data={filter(dialers, ['name', 'api_url', 'company_name', 'branch_name'])} /> },
    { key: 'notifications', label: <Space size={6}><NotificationOutlined />Notifications</Space>, children: <AdminNotificationCenter users={users} companies={companies} branches={branches} /> },
    { key: 'security', label: <Space size={6}><SafetyCertificateOutlined />Security</Space>, children: <Card className="admin-table-card"><Table rowKey="id" rowClassName={() => 'admin-table-row'} columns={eventColumns} dataSource={securityEvents} loading={{ spinning: loading, delay: 180, description: 'Updating security events' }} pagination={{ pageSize: 12, showSizeChanger: false }} scroll={{ x: 760 }} /></Card> },
  ];

  return (
    <div className="page-stack administration-page">
      <section className="admin-hero">
        <div className="admin-hero__mesh" />
        <div className="admin-hero__copy"><Title level={2}>Administration</Title></div>
        <Space wrap><Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>Refresh</Button><Button type="primary" icon={<PlusOutlined />} onClick={() => { setActiveTab('companies'); openEditor('companies'); }}>Add company</Button></Space>
      </section>
      {loadError && <Alert type="error" showIcon title="Unable to load administration" description={loadError} action={<Button onClick={() => void load()}>Try again</Button>} />}
      <Tabs activeKey={activeTab} onChange={(key) => { setActiveTab(key); setQuery(''); }} items={tabs} animated={{ inkBar: true, tabPane: true }} className="admin-tabs" classNames={{ header: 'admin-tabs__header' }} />
      <EditorDrawer editor={editor} form={form} saving={saving} companies={companies} branches={branches} users={users} dialers={dialers} selectedCompany={selectedCompany} selectedBranch={selectedBranch} selectedRole={selectedRole} onClose={() => setEditor(null)} onSave={save} />
      <ProjectAccessDrawer user={projectEditor} form={projectForm} dialers={dialers} saving={projectSaving} onClose={() => { setProjectEditor(null); projectForm.resetFields(); }} onSave={saveProjectAccess} />
    </div>
  );
}

function AdministrationOverview({ summary, events, loading, onNavigate }: { summary: AdminSummary | null; events: SecurityEvent[]; loading: boolean; onNavigate: (key: string) => void }) {
  const cards = [
    { label: 'Companies', value: summary?.companies ?? 0, detail: `${summary?.branches ?? 0} branches`, icon: <BankOutlined />, tab: 'companies' },
    { label: 'Teams', value: summary?.teams ?? 0, detail: `${summary?.active_teams ?? 0} active`, icon: <ClusterOutlined />, tab: 'teams' },
    { label: 'Portal users', value: summary?.users ?? 0, detail: `${summary?.active_users ?? 0} active`, icon: <TeamOutlined />, tab: 'users' },
    { label: 'Dialer connections', value: summary?.dialers ?? 0, detail: `${summary?.active_dialers ?? 0} online`, icon: <ApiOutlined />, tab: 'dialers' },
  ];
  if (loading) return <ContentLoader label="Loading administration overview" minHeight={420} />;
  return <div className="admin-overview data-reveal">
    <Row gutter={[16, 16]}>{cards.map((card, index) => <Col xs={24} sm={12} xl={6} key={card.label}><Card hoverable className={`admin-stat admin-stat--${index}`} onClick={() => card.tab && onNavigate(card.tab)}><span className="admin-stat__icon">{card.icon}</span><Statistic title={card.label} value={card.value} /><Text type="secondary">{card.detail}</Text></Card></Col>)}</Row>
    <Row gutter={[16, 16]}>
      <Col xs={24} xl={15}><Card className="admin-command-card" title="Configuration health"><div className="health-grid"><HealthItem label="Organization structure" detail={`${summary?.companies ?? 0} companies · ${summary?.branches ?? 0} branches`} complete={Boolean(summary?.companies && summary?.branches)} /><HealthItem label="User access" detail={`${summary?.active_users ?? 0} active users`} complete={Boolean(summary?.active_users)} /><HealthItem label="Dialer intake" detail={`${summary?.active_dialers ?? 0} active connections`} complete={Boolean(summary?.active_dialers)} /></div></Card></Col>
      <Col xs={24} xl={9}><Card className="admin-command-card" title="Recent security activity" extra={<Button type="link" onClick={() => onNavigate('security')}>View all</Button>}><div className="security-feed">{events.length ? events.map((event) => <div key={event.id}><span className={`event-dot event-dot--${event.event.includes('failure') ? 'danger' : 'success'}`} /><span><strong>{event.event_label}</strong><small>{event.email || 'System'} · {appDate(event.created_at).format('DD MMM, h:mm A')} ET</small></span></div>) : <Text type="secondary">No security events recorded yet.</Text>}</div></Card></Col>
    </Row>
  </div>;
}

function ResourceTable<T extends { id: string }>({ resource, query, onQuery, loading, onAdd, columns, data }: { resource: Resource; query: string; onQuery: (value: string) => void; loading: boolean; onAdd: () => void; columns: TableProps<T>['columns']; data: T[] }) {
  return <Card className="admin-table-card" title={<strong>{resourceLabels[resource].plural}</strong>} extra={<Space wrap><Input prefix={<SearchOutlined />} allowClear placeholder={`Search ${resourceLabels[resource].plural.toLowerCase()}`} value={query} onChange={(event) => onQuery(event.target.value)} className="admin-search" /><Button type="primary" icon={<PlusOutlined />} onClick={onAdd}>Add {resourceLabels[resource].singular}</Button></Space>}><Table<T> rowKey="id" rowClassName={() => 'admin-table-row'} columns={columns} dataSource={data} loading={{ spinning: loading, delay: 180, description: `Updating ${resourceLabels[resource].plural.toLowerCase()}` }} pagination={{ pageSize: 10, showSizeChanger: false, showTotal: (total) => `${total} records` }} scroll={{ x: 820 }} /></Card>;
}

function ProjectManagerAccessTable({ query, onQuery, loading, managers, columns, onAdd }: { query: string; onQuery: (value: string) => void; loading: boolean; managers: AdminUserRecord[]; columns: TableProps<AdminUserRecord>['columns']; onAdd: () => void }) {
  return <Card className="admin-table-card" title={<strong>Project Manager access</strong>} extra={<Space wrap><Input prefix={<SearchOutlined />} allowClear placeholder="Search project managers" value={query} onChange={(event) => onQuery(event.target.value)} className="admin-search" /><Button type="primary" icon={<PlusOutlined />} onClick={onAdd}>Add Project Manager</Button></Space>}><Table<AdminUserRecord> rowKey="id" rowClassName={() => 'admin-table-row'} columns={columns} dataSource={managers} loading={{ spinning: loading, delay: 180, description: 'Updating project access' }} locale={{ emptyText: 'No Project Managers configured' }} pagination={{ pageSize: 10, showSizeChanger: false, showTotal: (total) => `${total} project managers` }} scroll={{ x: 900 }} /></Card>;
}

function EditorDrawer({ editor, form, saving, companies, branches, users, dialers, selectedCompany, selectedBranch, selectedRole, onClose, onSave }: { editor: EditorState; form: FormInstance; saving: boolean; companies: CompanyRecord[]; branches: BranchRecord[]; users: AdminUserRecord[]; dialers: DialerRecord[]; selectedCompany?: string; selectedBranch?: string; selectedRole?: AdminUserRecord['role']; onClose: () => void; onSave: (values: Record<string, unknown>) => Promise<void> }) {
  const resource = editor?.resource;
  const isEdit = Boolean(editor?.record);
  const companyOptions = companies.filter((company) => company.is_active || company.id === selectedCompany).map((company) => ({ value: company.id, label: company.name }));
  const branchOptions = branches.filter((branch) => (!selectedCompany || branch.company === selectedCompany) && (branch.is_active || branch.id === form.getFieldValue('branch'))).map((branch) => ({ value: branch.id, label: `${branch.name} · ${branch.code}` }));
  const leaderOptions = users.filter((user) => user.role === 'team_leader' && user.branch === selectedBranch && (user.is_active || user.id === form.getFieldValue('team_leader'))).map((user) => ({ value: user.id, label: `${user.name} · ${user.email}` }));
  const selectedProjectIds = (form.getFieldValue('project_assignment_ids') as string[] | undefined) ?? [];
  const projectOptions = dialers
    .filter((dialer) => dialer.branch === selectedBranch && (dialer.is_active || dialer.campaigns.some((project) => selectedProjectIds.includes(project.id))))
    .flatMap((dialer) => dialer.campaigns.map((project) => ({ value: project.id, label: `${dialer.name} · ${project.project_name} (${project.campaign})` })));
  return <Drawer open={Boolean(editor)} onClose={onClose} size="large" destroyOnHidden title={<div className="drawer-title"><span className="drawer-title__icon">{resource === 'teams' ? <ClusterOutlined /> : resource === 'users' ? <TeamOutlined /> : resource === 'dialers' ? <ApiOutlined /> : resource === 'branches' ? <ApartmentOutlined /> : <BankOutlined />}</span><span><strong>{isEdit ? 'Edit' : 'Add'} {resource ? resourceLabels[resource].singular : ''}</strong></span></div>} extra={<Space><Button onClick={onClose}>Cancel</Button><Button type="primary" loading={saving} onClick={() => form.submit()}>Save changes</Button></Space>}>
    <Form form={form} layout="vertical" requiredMark="optional" onFinish={onSave} className="admin-form">
      {resource === 'companies' && <><Form.Item name="name" label="Company name" rules={[{ required: true }]}><Input placeholder="e.g. Acme Operations" /></Form.Item><Form.Item name="slug" label="URL slug" rules={[{ required: true }, { pattern: /^[a-z0-9-]+$/, message: 'Use lowercase letters, numbers, and hyphens.' }]}><Input placeholder="acme-operations" /></Form.Item></>}
      {resource === 'branches' && <><Form.Item name="company" label="Company" rules={[{ required: true }]}><Select showSearch={{ optionFilterProp: 'label' }} options={companyOptions} placeholder="Select company" /></Form.Item><Form.Item name="name" label="Branch name" rules={[{ required: true }]}><Input placeholder="e.g. New York" /></Form.Item><Form.Item name="code" label="Branch code" rules={[{ required: true }, { pattern: /^[a-z0-9-]+$/ }]}><Input placeholder="nyc" /></Form.Item><Form.Item name="timezone" label="Timezone" rules={[{ required: true }]}><Select options={[{ value: 'America/New_York', label: 'Eastern Time — New York (EST/EDT)' }]} /></Form.Item></>}
      {resource === 'teams' && <><Form.Item name="branch" label="Branch" rules={[{ required: true }]}><Select showSearch={{ optionFilterProp: 'label' }} options={branches.map((branch) => ({ value: branch.id, label: `${branch.company_name} · ${branch.name}` }))} onChange={() => form.setFieldValue('team_leader', undefined)} placeholder="Select branch" /></Form.Item><Form.Item name="name" label="Team name" extra="Prefix before the hyphen in agent_full_name." rules={[{ required: true }]}><Input placeholder="e.g. Annihilators" /></Form.Item><Form.Item name="avatar" label="Team avatar" rules={[{ required: true, message: 'Choose a team avatar.' }]}><TeamAvatarPicker /></Form.Item><Form.Item name="team_leader" label="Team leader" rules={[{ required: true }]}><Select showSearch={{ optionFilterProp: 'label' }} options={leaderOptions} disabled={!selectedBranch} placeholder={selectedBranch ? 'Select a team leader' : 'Select a branch first'} /></Form.Item></>}
      {resource === 'users' && <><Row gutter={14}><Col span={12}><Form.Item name="first_name" label="First name" rules={[{ required: true }]}><Input /></Form.Item></Col><Col span={12}><Form.Item name="last_name" label="Last name" rules={[{ required: true }]}><Input /></Form.Item></Col></Row><Form.Item name="email" label="Work email" rules={[{ required: true }, { type: 'email' }]}><Input /></Form.Item><Form.Item name="role" label="Portal role" rules={[{ required: true }]}><Select options={roleOptions} onChange={(role) => { if (!['qa', 'team_leader', 'project_manager'].includes(role)) form.setFieldValue('project_assignment_ids', []); }} /></Form.Item><Form.Item name="company" label="Company" rules={[{ required: true }]}><Select showSearch={{ optionFilterProp: 'label' }} options={companyOptions} onChange={() => { form.setFieldValue('branch', undefined); form.setFieldValue('project_assignment_ids', []); }} /></Form.Item><Form.Item name="branch" label="Branch" rules={[{ required: true }]}><Select showSearch={{ optionFilterProp: 'label' }} options={branchOptions} disabled={!selectedCompany} onChange={() => form.setFieldValue('project_assignment_ids', [])} /></Form.Item>{selectedRole && ['qa', 'team_leader', 'project_manager'].includes(selectedRole) && <Form.Item name="project_assignment_ids" label="Dialer projects" rules={selectedRole === 'team_leader' ? [] : [{ required: true, message: 'Assign at least one dialer project.' }]}><Select mode="multiple" allowClear showSearch={{ optionFilterProp: 'label' }} options={projectOptions} disabled={!selectedBranch} maxTagCount="responsive" placeholder={selectedBranch ? 'Select allowed projects' : 'Select a branch first'} /></Form.Item>}<Form.Item name="password" label={isEdit ? 'New temporary password' : 'Temporary password'} extra={isEdit ? 'Leave blank to keep current password.' : undefined} rules={isEdit ? [{ min: 12 }] : [{ required: true }, { min: 12 }]}><Input.Password prefix={<KeyOutlined />} autoComplete="new-password" /></Form.Item><Form.Item name="must_change_password" label="Require password change" valuePropName="checked"><Switch /></Form.Item></>}
      {resource === 'dialers' && <><Form.Item name="branch" label="Mapped branch" rules={[{ required: true }]}><Select showSearch={{ optionFilterProp: 'label' }} options={branches.map((branch) => ({ value: branch.id, label: `${branch.company_name} · ${branch.name}` }))} /></Form.Item><Form.Item name="name" label="Connection name" rules={[{ required: true }]}><Input placeholder="Primary VICIdial" /></Form.Item><Form.Item name="api_url" label="VICIdial API URL" rules={[{ required: true }, { type: 'url' }]}><Input placeholder="https://dialer.example.com/non_agent_api.php" /></Form.Item><Row gutter={14}><Col span={12}><Form.Item name="api_username" label="API username" rules={[{ required: true }]}><Input /></Form.Item></Col><Col span={12}><Form.Item name="api_source" label="API source" rules={[{ required: true }]}><Input /></Form.Item></Col></Row><Form.Item name="api_password" label={isEdit ? 'Replace API password' : 'API password'} extra={isEdit ? 'Leave blank to retain current credential.' : undefined} rules={isEdit ? [] : [{ required: true }]}><Input.Password autoComplete="new-password" /></Form.Item><Form.Item name="webhook_secret" label={isEdit ? 'Rotate webhook secret' : 'Webhook secret'} extra={isEdit ? 'Leave blank to retain current secret.' : undefined} rules={isEdit ? [] : [{ required: true }, { min: 24 }]}><Input.Password autoComplete="new-password" /></Form.Item><div className="campaign-mapping-editor"><div className="campaign-mapping-editor__heading"><strong>Campaign projects</strong></div><Form.List name="campaigns">{(fields, { add, remove }) => <div className="campaign-mapping-editor__list">{fields.map(({ key, name, ...restField }, index) => <Row gutter={10} align="middle" key={key}><Col flex="1 1 180px"><Form.Item {...restField} name={[name, 'campaign']} label={index === 0 ? 'Campaign code' : undefined} rules={[{ required: true, message: 'Enter a campaign code.' }]}><Input placeholder="e.g. RETENTION" /></Form.Item></Col><Col flex="1 1 220px"><Form.Item {...restField} name={[name, 'project_name']} label={index === 0 ? 'Project name' : undefined} rules={[{ required: true, message: 'Enter a project name.' }]}><Input placeholder="e.g. Customer Retention" /></Form.Item></Col><Col flex="36px" className={index === 0 ? 'campaign-mapping-editor__remove--labelled' : ''}><Button type="text" danger shape="circle" icon={<MinusCircleOutlined />} aria-label={`Remove campaign mapping ${index + 1}`} onClick={() => remove(name)} /></Col></Row>)}<Button type="dashed" block icon={<PlusOutlined />} onClick={() => add({ campaign: '', project_name: '' })}>Add campaign mapping</Button></div>}</Form.List></div><Form.Item name="request_timeout_seconds" label="Request timeout (seconds)" rules={[{ required: true }]}><Input type="number" min={5} max={120} /></Form.Item></>}
      <div className="form-status-row"><span><strong>Active</strong></span><Form.Item name="is_active" valuePropName="checked" noStyle><Switch /></Form.Item></div>
    </Form>
  </Drawer>;
}

function ProjectAccessCell({ projects, onManage }: { projects: AdminUserRecord['assigned_projects']; onManage: () => void }) {
  return <div className="project-access-cell">
    <div className="project-access-cell__projects">
      {projects.length ? <>{projects.slice(0, 2).map((project) => <Tag className="project-access-tag" key={project.id} color="blue">{project.project_name}</Tag>)}{projects.length > 2 && <Tag className="project-access-tag">+{projects.length - 2}</Tag>}</> : <Text type="secondary">No projects assigned</Text>}
    </div>
    <Button type="link" size="small" icon={<ProjectOutlined />} onClick={onManage}>{projects.length ? 'Manage' : 'Assign'}</Button>
  </div>;
}

function ProjectAccessDrawer({ user, form, dialers, saving, onClose, onSave }: { user: AdminUserRecord | null; form: FormInstance; dialers: DialerRecord[]; saving: boolean; onClose: () => void; onSave: (values: { project_assignment_ids?: string[] }) => Promise<void> }) {
  const roleLabel = user?.role === 'project_manager' ? 'Project Manager' : user?.role === 'qa' ? 'QA analyst' : 'Team Leader';
  useEffect(() => {
    if (!user) return;
    form.setFieldsValue({ project_assignment_ids: user.assigned_projects.map((project) => project.id) });
  }, [form, user]);
  const projectOptions = user ? dialers
    .filter((dialer) => dialer.branch === user.branch)
    .flatMap((dialer) => dialer.campaigns.map((project) => ({ value: project.id, label: `${project.project_name} · ${dialer.name} (${project.campaign})` }))) : [];
  return <Drawer
    open={Boolean(user)}
    onClose={onClose}
    size="large"
    destroyOnHidden
    title={<div className="drawer-title"><span className="drawer-title__icon"><ProjectOutlined /></span><span><strong>{roleLabel} project access</strong><small>{user?.name ?? roleLabel}</small></span></div>}
    extra={<Space><Button onClick={onClose}>Cancel</Button><Button type="primary" loading={saving} onClick={() => form.submit()}>Save access</Button></Space>}
  >
    {user && <div className="project-access-drawer">
      <div className="project-access-drawer__identity"><Avatar size={42}>{`${user.first_name[0] ?? ''}${user.last_name[0] ?? ''}`}</Avatar><span><strong>{user.name}</strong><small>{user.email} · {user.company_name} · {user.branch_name}</small></span></div>
      <Form form={form} layout="vertical" requiredMark="optional" onFinish={onSave} clearOnDestroy>
        <Form.Item name="project_assignment_ids" label="Assigned projects" rules={user.role === 'team_leader' ? [] : [{ required: true, message: 'Assign at least one project.' }]}>
          <Select mode="multiple" allowClear showSearch={{ optionFilterProp: 'label' }} options={projectOptions} maxTagCount="responsive" placeholder={projectOptions.length ? 'Select projects' : 'No campaign projects are configured for this branch'} disabled={!projectOptions.length} />
        </Form.Item>
      </Form>
    </div>}
  </Drawer>;
}

function EntityCell({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) { return <div className="entity-cell"><span className="entity-cell__icon">{icon}</span><span><strong>{title}</strong><small>{detail}</small></span></div>; }
function StatusSwitch({ checked, onChange }: { checked: boolean; onChange: (checked: boolean) => void }) { return <Space size={8}><Switch size="small" checked={checked} onChange={onChange} /><Text type="secondary">{checked ? 'Active' : 'Paused'}</Text></Space>; }
function EditButton({ onClick }: { onClick: () => void }) { return <Tooltip title="Edit"><Button type="text" shape="circle" icon={<EditOutlined />} onClick={onClick} /></Tooltip>; }
function TabLabel({ label, count }: { label: string; count: number }) { return <Space size={7}>{label}<span className="tab-count">{count}</span></Space>; }
function HealthItem({ label, detail, complete }: { label: string; detail: string; complete: boolean }) { return <div className="health-item"><span className={`health-item__icon ${complete ? 'health-item__icon--complete' : ''}`}>{complete ? <CheckCircleFilled /> : <span />}</span><span><strong>{label}</strong><small>{detail}</small></span><Tag color={complete ? 'success' : 'warning'}>{complete ? 'Ready' : 'Action needed'}</Tag></div>; }
