import { CustomerServiceOutlined, ReloadOutlined } from '@ant-design/icons';
import { Button, Card, Table, Tag, Typography, type TableProps } from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useState } from 'react';
import { api } from '../lib/api';
import type { CallEvent } from '../types';

const { Title, Paragraph } = Typography;
const statusColor: Record<string, string> = { downloaded: 'success', downloading: 'processing', retrying: 'warning', failed: 'error', skipped: 'default', pending: 'default' };

export function CallsPage() {
  const [calls, setCalls] = useState<CallEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const load = useCallback(() => { setLoading(true); api<CallEvent[]>('/api/v1/calls/').then(setCalls).finally(() => setLoading(false)); }, []);
  useEffect(() => {
    let active = true;
    api<CallEvent[]>('/api/v1/calls/')
      .then((result) => { if (active) setCalls(result); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  const columns: TableProps<CallEvent>['columns'] = [
    { title: 'Call ID', dataIndex: 'call_id', key: 'call_id', render: (value, row) => <strong>{value || row.lead_id || '—'}</strong> },
    { title: 'Agent', dataIndex: 'agent_user', key: 'agent_user' },
    { title: 'Campaign', dataIndex: 'campaign', key: 'campaign', render: (value) => <Tag>{value || '—'}</Tag> },
    { title: 'Phone', dataIndex: 'phone_number', key: 'phone_number' },
    { title: 'Disposition', dataIndex: 'disposition', key: 'disposition', render: (value) => <Tag color="blue">{value || '—'}</Tag> },
    { title: 'Talk time', dataIndex: 'talk_time', key: 'talk_time', render: (value) => `${Math.floor(value / 60)}m ${value % 60}s` },
    { title: 'Recording', dataIndex: 'recording_download_status', key: 'recording', render: (value) => <Tag color={statusColor[value]}>{value.replace('_', ' ')}</Tag> },
    { title: 'Received', dataIndex: 'received_at', key: 'received_at', render: (value) => dayjs(value).format('DD MMM, h:mm A') },
  ];
  return <div className="page-stack"><div className="page-heading"><div><Title level={2}>Call library</Title><Paragraph>All dialer calls available to your branch.</Paragraph></div><Button icon={<ReloadOutlined />} onClick={load}>Refresh</Button></div><Card className="content-card"><Table rowKey="id" columns={columns} dataSource={calls} loading={loading} scroll={{ x: 960 }} pagination={{ pageSize: 20, showSizeChanger: false }} locale={{ emptyText: <div className="empty-table"><CustomerServiceOutlined /><strong>No calls found</strong><span>New dialer events will appear here automatically.</span></div> }} /></Card></div>;
}
