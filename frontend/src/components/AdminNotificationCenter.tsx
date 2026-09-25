import {
  ApartmentOutlined,
  BankOutlined,
  BellOutlined,
  GlobalOutlined,
  SendOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons';
import {
  App as AntApp,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  Row,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  type TableProps,
} from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '../lib/api';
import { appDate } from '../lib/datetime';
import type {
  AdminNotificationBroadcast,
  AdminNotificationHistory,
  AdminUserRecord,
  BranchRecord,
  CompanyRecord,
  NotificationAudience,
} from '../types';

const { Text } = Typography;

type NotificationFormValues = {
  audience: NotificationAudience;
  target_ids?: string[];
  severity: AdminNotificationBroadcast['severity'];
  title: string;
  message: string;
};

const audienceOptions = [
  { value: 'all', label: 'Everyone', icon: <GlobalOutlined /> },
  { value: 'users', label: 'Selected users', icon: <UserOutlined /> },
  { value: 'roles', label: 'Roles', icon: <TeamOutlined /> },
  { value: 'companies', label: 'Companies', icon: <BankOutlined /> },
  { value: 'branches', label: 'Branches', icon: <ApartmentOutlined /> },
];

const roleOptions = [
  { value: 'qa', label: 'QA Analysts' },
  { value: 'team_leader', label: 'Team Leaders' },
  { value: 'project_manager', label: 'Project Managers' },
  { value: 'supervisor', label: 'Supervisors' },
];

const severityColors = { info: 'blue', warning: 'gold', error: 'red' } as const;

export function AdminNotificationCenter({ users, companies, branches }: { users: AdminUserRecord[]; companies: CompanyRecord[]; branches: BranchRecord[] }) {
  const { message, modal } = AntApp.useApp();
  const [form] = Form.useForm<NotificationFormValues>();
  const [history, setHistory] = useState<AdminNotificationBroadcast[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const audience = Form.useWatch('audience', form) ?? 'all';
  const targetIds = Form.useWatch('target_ids', form);
  const activeUsers = useMemo(() => users.filter((user) => user.is_active), [users]);

  const loadHistory = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api<AdminNotificationHistory>('/api/v1/notifications/admin/broadcasts/');
      setHistory(result.results);
    } catch (error) {
      message.error(error instanceof ApiError ? error.message : 'Notification history could not be loaded.');
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => void loadHistory());
    return () => window.cancelAnimationFrame(frame);
  }, [loadHistory]);

  const recipientCount = useMemo(() => {
    const selected = new Set(targetIds ?? []);
    if (audience === 'all') return activeUsers.length;
    if (audience === 'users') return activeUsers.filter((user) => selected.has(user.id)).length;
    if (audience === 'roles') return activeUsers.filter((user) => selected.has(user.role)).length;
    if (audience === 'companies') return activeUsers.filter((user) => selected.has(user.company)).length;
    return activeUsers.filter((user) => selected.has(user.branch)).length;
  }, [activeUsers, audience, targetIds]);

  const targetOptions = useMemo(() => {
    if (audience === 'users') return activeUsers.map((user) => ({ value: user.id, label: `${user.name} · ${user.email}` }));
    if (audience === 'roles') return roleOptions;
    if (audience === 'companies') return companies.map((company) => ({ value: company.id, label: company.name }));
    if (audience === 'branches') return branches.map((branch) => ({ value: branch.id, label: `${branch.company_name} · ${branch.name}` }));
    return [];
  }, [activeUsers, audience, branches, companies]);

  const send = async (values: NotificationFormValues) => {
    setSending(true);
    try {
      const result = await api<AdminNotificationBroadcast>('/api/v1/notifications/admin/broadcasts/', {
        method: 'POST',
        body: JSON.stringify({ ...values, target_ids: values.target_ids ?? [] }),
      });
      message.success(`Notification sent to ${result.recipient_count.toLocaleString()} user${result.recipient_count === 1 ? '' : 's'}.`);
      form.resetFields();
      await loadHistory();
    } catch (error) {
      message.error(error instanceof ApiError ? error.message : 'The notification could not be sent.');
      throw error;
    } finally {
      setSending(false);
    }
  };

  const confirmSend = (values: NotificationFormValues) => {
    if (!recipientCount) {
      void message.warning('The selected audience has no active users.');
      return;
    }
    modal.confirm({
      title: 'Send this notification?',
      content: `It will be delivered to ${recipientCount.toLocaleString()} active user${recipientCount === 1 ? '' : 's'} immediately.`,
      okText: 'Send notification',
      cancelText: 'Review message',
      icon: <SendOutlined />,
      onOk: () => send(values),
    });
  };

  const columns: TableProps<AdminNotificationBroadcast>['columns'] = [
    { title: 'Notification', key: 'notification', render: (_, item) => <div className="notification-history-copy"><strong>{item.title}</strong><span>{item.message}</span></div> },
    { title: 'Audience', dataIndex: 'audience_label', key: 'audience', width: 230, render: (value) => <Text>{value}</Text> },
    { title: 'Delivery', key: 'delivery', width: 130, render: (_, item) => <div className="notification-delivery"><strong>{item.read_count}/{item.recipient_count}</strong><small>read</small></div> },
    { title: 'Priority', dataIndex: 'severity', key: 'severity', width: 110, render: (value: AdminNotificationBroadcast['severity']) => <Tag color={severityColors[value]}>{value}</Tag> },
    { title: 'Sent', key: 'sent', width: 180, render: (_, item) => <div className="notification-sent"><strong>{appDate(item.created_at).format('DD MMM, h:mm A')} ET</strong><small>{item.sender_name}</small></div> },
  ];

  return <div className="admin-notification-center data-reveal">
    <Card className="notification-compose-card" title={<Space><BellOutlined /><strong>Send notification</strong></Space>} extra={<Tag color={recipientCount ? 'blue' : 'default'}>{recipientCount.toLocaleString()} recipient{recipientCount === 1 ? '' : 's'}</Tag>}>
      <Form<NotificationFormValues> form={form} layout="vertical" requiredMark={false} initialValues={{ audience: 'all', severity: 'info', target_ids: [] }} onFinish={confirmSend}>
        <Row gutter={16}>
          <Col xs={24} lg={14}>
            <Form.Item name="audience" label="Audience" rules={[{ required: true }]}>
              <Select options={audienceOptions} onChange={() => form.setFieldValue('target_ids', [])} />
            </Form.Item>
          </Col>
          <Col xs={24} lg={10}>
            <Form.Item name="severity" label="Priority" rules={[{ required: true }]}>
              <Segmented block options={[{ label: 'Information', value: 'info' }, { label: 'Important', value: 'warning' }, { label: 'Urgent', value: 'error' }]} />
            </Form.Item>
          </Col>
        </Row>
        {audience !== 'all' && <Form.Item name="target_ids" label={audienceOptions.find((item) => item.value === audience)?.label} rules={[{ required: true, message: 'Choose at least one audience target.' }]}>
          <Select mode="multiple" allowClear showSearch={{ optionFilterProp: 'label' }} maxTagCount="responsive" options={targetOptions} placeholder="Choose recipients" />
        </Form.Item>}
        <Form.Item name="title" label="Title" rules={[{ required: true, whitespace: true, message: 'Enter a notification title.' }, { max: 120 }]}>
          <Input maxLength={120} placeholder="Write a clear, specific title" />
        </Form.Item>
        <Form.Item name="message" label="Message" rules={[{ required: true, whitespace: true, message: 'Enter the notification message.' }, { max: 1000 }]}>
          <Input.TextArea autoSize={{ minRows: 4, maxRows: 8 }} maxLength={1000} showCount placeholder="Tell recipients what they need to know" />
        </Form.Item>
        <div className="notification-compose-footer">
          <div><BellOutlined /><span><strong>{recipientCount.toLocaleString()} active recipient{recipientCount === 1 ? '' : 's'}</strong><small>Delivered in-app and through browser notifications when permitted</small></span></div>
          <Button type="primary" htmlType="submit" icon={<SendOutlined />} loading={sending}>Review and send</Button>
        </div>
      </Form>
    </Card>

    <Card className="admin-table-card notification-history-card" title={<strong>Delivery history</strong>}>
      <Table<AdminNotificationBroadcast>
        rowKey="id"
        columns={columns}
        dataSource={history}
        loading={{ spinning: loading, delay: 180, description: 'Updating notification history' }}
        pagination={{ pageSize: 8, showSizeChanger: false, showTotal: (total) => `${total} notifications` }}
        scroll={{ x: 920 }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No custom notifications sent yet" /> }}
      />
    </Card>
  </div>;
}
