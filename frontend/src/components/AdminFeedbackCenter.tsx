import { CheckCircleOutlined, EyeOutlined, MessageOutlined } from '@ant-design/icons';
import { App as AntApp, Button, Card, Empty, Image, Space, Table, Tag, Typography, type TableProps } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../lib/api';
import { appDate } from '../lib/datetime';
import type { FeedbackRecord, FeedbackResponse } from '../types';

const { Text } = Typography;

export function AdminFeedbackCenter() {
  const { message } = AntApp.useApp();
  const [items, setItems] = useState<FeedbackRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api<FeedbackResponse>('/api/v1/feedback/admin/');
      setItems(result.results);
    } catch (error) {
      message.error(error instanceof ApiError ? error.message : 'Feedback could not be loaded.');
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => void load());
    return () => window.cancelAnimationFrame(frame);
  }, [load]);

  const markReviewed = async (item: FeedbackRecord) => {
    setSavingId(item.id);
    try {
      const updated = await api<FeedbackRecord>(`/api/v1/feedback/admin/${item.id}/`, {
        method: 'PATCH',
        body: JSON.stringify({ reviewed: item.status !== 'reviewed' }),
      });
      setItems((current) => current.map((entry) => entry.id === updated.id ? updated : entry));
      message.success(updated.status === 'reviewed' ? 'Feedback marked as reviewed.' : 'Feedback reopened.');
    } catch (error) {
      message.error(error instanceof ApiError ? error.message : 'Feedback status could not be updated.');
    } finally {
      setSavingId(null);
    }
  };

  const columns: TableProps<FeedbackRecord>['columns'] = [
    {
      title: 'Submitted by',
      key: 'user',
      width: 230,
      render: (_, item) => <div className="feedback-user-cell"><strong>{item.user.name}</strong><span>{item.user.email}</span><small>{item.user.role} · {item.user.company} · {item.user.branch}</small></div>,
    },
    {
      title: 'Feedback',
      key: 'message',
      render: (_, item) => <div className="feedback-message-cell"><span>{item.message}</span>{item.images.length > 0 && <Image.PreviewGroup><div className="feedback-image-strip">{item.images.map((image) => <Image key={image.id} src={image.url} width={58} height={58} preview={{ mask: <EyeOutlined /> }} alt={image.name || 'Feedback attachment'} />)}</div></Image.PreviewGroup>}</div>,
    },
    {
      title: 'Submitted',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (value: string) => <Text>{appDate(value).format('DD MMM YYYY, h:mm A')} ET</Text>,
    },
    {
      title: 'Status',
      key: 'status',
      width: 135,
      render: (_, item) => item.status === 'reviewed' ? <div className="feedback-status"><Tag color="success">Reviewed</Tag>{item.reviewed_by && <small>{item.reviewed_by}</small>}</div> : <Tag color="gold">Open</Tag>,
    },
    {
      title: '',
      key: 'actions',
      width: 150,
      render: (_, item) => <Button size="small" type={item.status === 'reviewed' ? 'default' : 'primary'} icon={item.status === 'reviewed' ? <MessageOutlined /> : <CheckCircleOutlined />} loading={savingId === item.id} onClick={() => void markReviewed(item)}>{item.status === 'reviewed' ? 'Reopen' : 'Mark reviewed'}</Button>,
    },
  ];

  return <Card className="admin-table-card feedback-admin-card" title={<Space><MessageOutlined /><strong>User feedback</strong></Space>}>
    <Table<FeedbackRecord>
      rowKey="id"
      columns={columns}
      dataSource={items}
      loading={{ spinning: loading, delay: 180, description: 'Loading feedback' }}
      pagination={{ pageSize: 10, showSizeChanger: false, showTotal: (total) => `${total} feedback item${total === 1 ? '' : 's'}` }}
      scroll={{ x: 1050 }}
      locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No feedback submitted yet" /> }}
    />
  </Card>;
}
