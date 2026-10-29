import {
  CheckCircleOutlined,
  EditOutlined,
  ReloadOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import {
  App as AntApp,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  Row,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  type TableProps,
} from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api, ApiError } from '../lib/api';
import { appDate } from '../lib/datetime';
import type { CallEvent, PaginatedResponse } from '../types';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

type EditorFormValues = {
  disposition: string;
  client_20_plus: boolean;
  client_30_plus: boolean;
  client_status: string | null;
  sold: boolean;
  preset: string | null;
};

export function CallEditorPage() {
  const { message } = AntApp.useApp();
  const [searchParams, setSearchParams] = useSearchParams();
  const [search, setSearch] = useState('');
  const [disposition, setDisposition] = useState('');
  const [dates, setDates] = useState<[Dayjs, Dayjs] | null>(null);
  const [rows, setRows] = useState<CallEvent[]>([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<CallEvent | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<EditorFormValues>();
  const selectedDisposition = Form.useWatch('disposition', form)?.trim().toUpperCase();
  const isSale = selectedDisposition === 'SALE';

  const load = useCallback(async (targetPage = page, overrides?: { search?: string; disposition?: string; dates?: [Dayjs, Dayjs] | null }) => {
    setLoading(true);
    try {
      const query = new URLSearchParams({ page: String(targetPage), page_size: '20' });
      const activeSearch = overrides?.search ?? search;
      const activeDisposition = overrides?.disposition ?? disposition;
      const activeDates = overrides?.dates === undefined ? dates : overrides.dates;
      if (activeSearch.trim()) query.set('search', activeSearch.trim());
      if (activeDisposition.trim()) query.set('disposition', activeDisposition.trim());
      if (activeDates) {
        query.set('date_from', activeDates[0].format('YYYY-MM-DD'));
        query.set('date_to', activeDates[1].format('YYYY-MM-DD'));
      }
      const result = await api<PaginatedResponse<CallEvent>>(`/api/v1/calls/editor/?${query}`);
      setRows(result.results);
      setCount(result.count);
      setPage(targetPage);
    } catch (error) {
      message.error(error instanceof ApiError ? error.message : 'Call records could not be loaded.');
    } finally {
      setLoading(false);
    }
  }, [dates, disposition, message, page, search]);

  const openCall = useCallback(async (call: CallEvent | string) => {
    try {
      const record = typeof call === 'string'
        ? await api<CallEvent>(`/api/v1/calls/editor/${call}/`)
        : call;
      setSelected(record);
      form.setFieldsValue({
        disposition: record.disposition,
        client_20_plus: record.client_20_plus,
        client_30_plus: record.client_30_plus,
        client_status: record.client_status,
        sold: record.sold,
        preset: record.preset,
      });
    } catch (error) {
      message.error(error instanceof ApiError ? error.message : 'The call could not be opened.');
    }
  }, [form, message]);

  useEffect(() => { void load(1); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const callId = searchParams.get('call');
    if (callId) void openCall(callId);
  }, [openCall, searchParams]);

  const closeEditor = () => {
    setSelected(null);
    form.resetFields();
    if (searchParams.has('call')) {
      const next = new URLSearchParams(searchParams);
      next.delete('call');
      setSearchParams(next, { replace: true });
    }
  };

  const save = async (values: EditorFormValues) => {
    if (!selected) return;
    setSaving(true);
    try {
      const updated = await api<CallEvent>(`/api/v1/calls/editor/${selected.id}/`, {
        method: 'PATCH',
        body: JSON.stringify(values),
      });
      setSelected(updated);
      form.setFieldsValue({
        disposition: updated.disposition,
        client_20_plus: updated.client_20_plus,
        client_30_plus: updated.client_30_plus,
        client_status: updated.client_status,
        sold: updated.sold,
        preset: updated.preset,
      });
      setRows((current) => current.map((row) => row.id === updated.id ? updated : row));
      message.success('Call record updated.');
    } catch (error) {
      message.error(error instanceof ApiError ? error.message : 'The call could not be updated.');
    } finally {
      setSaving(false);
    }
  };

  const columns = useMemo<TableProps<CallEvent>['columns']>(() => [
    { title: 'Call', key: 'call', render: (_, row) => <span><strong>{row.phone_number || 'No phone'}</strong><br /><Text type="secondary">Lead {row.lead_id || '—'}</Text></span> },
    { title: 'Agent', key: 'agent', render: (_, row) => <span>{row.agent_name || row.agent_user || '—'}<br /><Text type="secondary">{row.project_name || row.campaign || 'Unmapped project'}</Text></span> },
    { title: 'Call date', dataIndex: 'call_date', key: 'call_date', width: 175, render: (value) => value ? `${appDate(value).format('DD MMM YYYY, h:mm A')} ET` : '—' },
    { title: 'Disposition', dataIndex: 'disposition', key: 'disposition', width: 110, render: (value) => <Tag color={value === 'SALE' ? 'success' : value === 'STALE' ? 'warning' : 'default'}>{value || '—'}</Tag> },
    { title: 'Preset', dataIndex: 'preset', key: 'preset', width: 120, render: (value) => value || <Text type="secondary">—</Text> },
    { title: 'Client time', key: 'client_time', width: 110, render: (_, row) => row.client_30_plus ? <Tag color="purple">30+</Tag> : row.client_20_plus ? <Tag color="blue">20+</Tag> : <Text type="secondary">—</Text> },
    { title: 'Sold', dataIndex: 'sold', key: 'sold', width: 80, render: (value) => value ? <CheckCircleOutlined style={{ fontSize: 18 }} /> : <Text type="secondary">No</Text> },
    { title: '', key: 'edit', width: 70, render: (_, row) => <Button type="text" icon={<EditOutlined />} onClick={() => void openCall(row)}>Edit</Button> },
  ], [openCall]);

  return <div className="page-stack">
    <div className="page-heading">
      <div><Title level={2}>Call editor</Title><Text type="secondary">Search and correct business fields for calls in your assigned projects.</Text></div>
    </div>

    <Card>
      <Row gutter={[12, 12]} align="bottom">
        <Col xs={24} lg={9}><Text strong>Search</Text><Input allowClear prefix={<SearchOutlined />} value={search} onChange={(event) => setSearch(event.target.value)} onPressEnter={() => void load(1)} placeholder="Phone, lead ID, call ID, agent, preset…" /></Col>
        <Col xs={24} sm={12} lg={5}><Text strong>Disposition</Text><Input allowClear value={disposition} onChange={(event) => setDisposition(event.target.value.toUpperCase())} onPressEnter={() => void load(1)} placeholder="e.g. SALE" /></Col>
        <Col xs={24} sm={12} lg={7}><Text strong>Call date</Text><RangePicker value={dates} onChange={(value) => setDates(value as [Dayjs, Dayjs] | null)} style={{ width: '100%' }} /></Col>
        <Col xs={24} lg={3}><Space><Button type="primary" icon={<SearchOutlined />} onClick={() => void load(1)}>Search</Button><Button icon={<ReloadOutlined />} onClick={() => { setSearch(''); setDisposition(''); setDates(null); void load(1, { search: '', disposition: '', dates: null }); }} /></Space></Col>
      </Row>
    </Card>

    <Card>
      <Table<CallEvent>
        rowKey="id"
        columns={columns}
        dataSource={rows}
        loading={loading}
        locale={{ emptyText: <Empty description="No calls match these filters" /> }}
        pagination={{ current: page, pageSize: 20, total: count, showSizeChanger: false, showTotal: (total) => `${total} calls`, onChange: (next) => void load(next) }}
        scroll={{ x: 1050 }}
      />
    </Card>

    <Drawer open={Boolean(selected)} onClose={closeEditor} size="large" destroyOnHidden title="Edit call record" extra={<Space><Button onClick={closeEditor}>Close</Button><Button type="primary" loading={saving} onClick={() => form.submit()}>Save changes</Button></Space>}>
      {selected && <>
        <Descriptions bordered size="small" column={2} style={{ marginBottom: 20 }}>
          <Descriptions.Item label="Phone">{selected.phone_number || '—'}</Descriptions.Item>
          <Descriptions.Item label="Lead ID">{selected.lead_id || '—'}</Descriptions.Item>
          <Descriptions.Item label="Call ID">{selected.call_id || '—'}</Descriptions.Item>
          <Descriptions.Item label="Agent">{selected.agent_name || selected.agent_user || '—'}</Descriptions.Item>
          <Descriptions.Item label="Project">{selected.project_name || '—'}</Descriptions.Item>
          <Descriptions.Item label="Dialer">{selected.dialer}</Descriptions.Item>
          <Descriptions.Item label="Call date">{selected.call_date ? `${appDate(selected.call_date).format('DD MMM YYYY, h:mm A')} ET` : '—'}</Descriptions.Item>
          <Descriptions.Item label="Stale">{selected.stale ? 'Yes — QA remains unavailable' : 'No'}</Descriptions.Item>
        </Descriptions>

        <Form form={form} layout="vertical" onFinish={save} requiredMark="optional">
          <Form.Item name="disposition" label="Disposition" rules={[{ required: true, message: 'Disposition is required.' }]}><Input onChange={(event) => { const next = event.target.value.toUpperCase(); form.setFieldValue('disposition', next); if (next !== 'SALE') form.setFieldsValue({ client_20_plus: false, client_30_plus: false, sold: false, preset: null }); }} /></Form.Item>
          <Row gutter={14}>
            <Col span={12}><Form.Item name="client_20_plus" label="Client side 20+ minutes" valuePropName="checked"><Switch disabled={!isSale} /></Form.Item></Col>
            <Col span={12}><Form.Item name="client_30_plus" label="Client side 30+ minutes" valuePropName="checked"><Switch disabled={!isSale} onChange={(checked) => { if (checked) form.setFieldValue('client_20_plus', true); }} /></Form.Item></Col>
          </Row>
          <Form.Item name="client_status" label="Client status"><Input allowClear placeholder="Optional client-side status" /></Form.Item>
          <Form.Item name="preset" label="Preset" extra={isSale ? 'Automatically resolved from VICIdial when available; editable for corrections.' : 'Preset is available only for SALE calls.'}><Input allowClear disabled={!isSale} placeholder="e.g. D42" /></Form.Item>
          <Form.Item name="sold" label="Mark sold" valuePropName="checked" extra="This is manual business confirmation and is never inferred from the dialer SALE disposition."><Switch disabled={!isSale} /></Form.Item>
        </Form>
      </>}
    </Drawer>
  </div>;
}
