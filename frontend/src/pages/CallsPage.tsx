import { CustomerServiceOutlined, PlayCircleOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Progress, Table, Tag, Tooltip, Typography, type TableProps } from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { AudioPlayerModal } from '../components/AudioPlayerModal';
import { CallLibraryFilters, type CallLibraryFilterValue } from '../components/CallLibraryFilters';
import { PortalLoader } from '../components/PortalLoader';
import { api } from '../lib/api';
import type { CallEvent, CallFilterOptions, PaginatedResponse } from '../types';

const { Title, Paragraph } = Typography;
const PAGE_CACHE_TTL_MS = 30_000;
const PAGE_CACHE_LIMIT = 20;

const DEFAULT_FILTERS: CallLibraryFilterValue = {
  search: '', agents: [], teams: [], campaigns: [], dispositions: [], dialers: [], eventTypes: [], recordingStatuses: [],
  dateField: 'received_at', dateFrom: '', dateTo: '', relativeRange: '', talkTimeMin: undefined, talkTimeMax: undefined, ordering: '-received_at',
};

type CachedCallPage = { cachedAt: number; response: PaginatedResponse<CallEvent> };

function listParameter(params: URLSearchParams, name: string) {
  return params.getAll(name).map((value) => value.trim()).filter(Boolean);
}

function numberParameter(params: URLSearchParams, name: string) {
  const raw = params.get(name);
  if (raw === null || raw === '') return undefined;
  const value = Number(raw);
  return Number.isSafeInteger(value) && value >= 0 ? value : undefined;
}

function filtersFromParams(params: URLSearchParams): CallLibraryFilterValue {
  return {
    search: params.get('search') ?? '',
    agents: listParameter(params, 'agent'), teams: listParameter(params, 'team'), campaigns: listParameter(params, 'campaign'),
    dispositions: listParameter(params, 'disposition'), dialers: listParameter(params, 'dialer'),
    eventTypes: listParameter(params, 'event_type'), recordingStatuses: listParameter(params, 'recording_status'),
    dateField: params.get('date_field') === 'call_date' ? 'call_date' : 'received_at',
    dateFrom: params.get('date_from') ?? '', dateTo: params.get('date_to') ?? '', relativeRange: params.get('time_range') ?? '',
    talkTimeMin: numberParameter(params, 'talk_time_min'), talkTimeMax: numberParameter(params, 'talk_time_max'),
    ordering: params.get('ordering') ?? '-received_at',
  };
}

function filterQuery(filters: CallLibraryFilterValue) {
  const query = new URLSearchParams();
  const values: Array<[string, string | number | undefined]> = [
    ['search', filters.search.trim()],
    ['date_field', filters.dateField === 'received_at' ? '' : filters.dateField], ['date_from', filters.dateFrom],
    ['date_to', filters.dateTo], ['time_range', filters.relativeRange], ['talk_time_min', filters.talkTimeMin], ['talk_time_max', filters.talkTimeMax],
    ['ordering', filters.ordering === '-received_at' ? '' : filters.ordering],
  ];
  values.forEach(([name, value]) => { if (value !== '' && value !== undefined) query.set(name, String(value)); });
  const multipleValues: Array<[string, string[]]> = [
    ['agent', filters.agents], ['team', filters.teams], ['campaign', filters.campaigns], ['disposition', filters.dispositions],
    ['dialer', filters.dialers], ['event_type', filters.eventTypes], ['recording_status', filters.recordingStatuses],
  ];
  multipleValues.forEach(([name, selected]) => selected.forEach((value) => query.append(name, value)));
  return query;
}

function recordingTooltip(call: CallEvent) {
  if (call.recording_available) return 'Play recording';
  const messages: Record<string, string> = {
    pending: 'Recording is not ready yet.', found: 'Recording was found and is waiting to download.',
    downloading: 'Recording is downloading now.', retrying: 'Recording download is being retried.',
    not_found: 'No recording was found for this call.', failed: 'Recording download failed.',
    skipped: 'Recording retrieval was skipped.',
  };
  return messages[call.recording_download_status] ?? 'Recording is not ready yet.';
}

export function CallsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [calls, setCalls] = useState<CallEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [currentPage, setCurrentPage] = useState(() => Math.max(1, Number(searchParams.get('page')) || 1));
  const [pageSize, setPageSize] = useState(() => [10, 20, 50, 100].includes(Number(searchParams.get('page_size'))) ? Number(searchParams.get('page_size')) : 20);
  const [total, setTotal] = useState(0);
  const [selectedCall, setSelectedCall] = useState<CallEvent | null>(null);
  const [filters, setFilters] = useState(() => filtersFromParams(searchParams));
  const [options, setOptions] = useState<CallFilterOptions | null>(null);
  const [optionsLoading, setOptionsLoading] = useState(true);
  const pageCache = useRef(new Map<string, CachedCallPage>());
  const serializedFilters = useMemo(() => filterQuery(filters).toString(), [filters]);

  useEffect(() => {
    const controller = new AbortController();
    api<CallFilterOptions>('/api/v1/calls/filter-options/', { signal: controller.signal })
      .then(setOptions)
      .catch((requestError: unknown) => { if (!(requestError instanceof DOMException && requestError.name === 'AbortError')) setOptions(null); })
      .finally(() => { if (!controller.signal.aborted) setOptionsLoading(false); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(serializedFilters);
    if (currentPage > 1) params.set('page', String(currentPage));
    if (pageSize !== 20) params.set('page_size', String(pageSize));
    setSearchParams(params, { replace: true });
  }, [currentPage, pageSize, serializedFilters, setSearchParams]);

  const load = useCallback((signal?: AbortSignal, force = false) => {
    const cacheKey = `${pageSize}:${currentPage}:${serializedFilters}`;
    const cachedPage = pageCache.current.get(cacheKey);
    if (!force && cachedPage && Date.now() - cachedPage.cachedAt < PAGE_CACHE_TTL_MS) {
      return Promise.resolve().then(() => {
        if (signal?.aborted) return;
        setCalls(cachedPage.response.results); setTotal(cachedPage.response.count); setError(''); setLoading(false);
      });
    }
    const query = new URLSearchParams(serializedFilters);
    query.set('page', String(currentPage)); query.set('page_size', String(pageSize));
    return api<PaginatedResponse<CallEvent>>(`/api/v1/calls/?${query}`, { signal })
      .then((result) => {
        if (signal?.aborted) return;
        if (pageCache.current.size >= PAGE_CACHE_LIMIT) {
          const oldestKey = pageCache.current.keys().next().value;
          if (oldestKey) pageCache.current.delete(oldestKey);
        }
        pageCache.current.set(cacheKey, { cachedAt: Date.now(), response: result });
        setCalls(result.results); setTotal(result.count); setError('');
      })
      .catch((requestError: unknown) => {
        if (requestError instanceof DOMException && requestError.name === 'AbortError') return;
        setCalls([]); setTotal(0); setError('The filters could not be applied. Check the selected ranges and try again.');
      })
      .finally(() => { if (!signal?.aborted) setLoading(false); });
  }, [currentPage, pageSize, serializedFilters]);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => void load(controller.signal), 350);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [load]);

  const columns: TableProps<CallEvent>['columns'] = [
    { title: 'Lead ID', dataIndex: 'lead_id', key: 'lead_id', render: (value) => <strong>{value || '—'}</strong> },
    { title: 'Agent', key: 'agent', render: (_, row) => <Tooltip title={row.agent_user ? `Agent ID: ${row.agent_user}` : 'Agent ID unavailable'}><span className="agent-name">{row.agent_name || row.agent_user || '—'}</span></Tooltip> },
    { title: 'Team', dataIndex: 'team_name', key: 'team_name', render: (value) => value ? <Tag>{value}</Tag> : '—' },
    { title: 'Campaign', dataIndex: 'campaign', key: 'campaign', render: (value) => <Tag>{value || '—'}</Tag> },
    { title: 'Phone number', dataIndex: 'phone_number', key: 'phone_number', render: (value) => value || '—' },
    { title: 'Disposition', dataIndex: 'disposition', key: 'disposition', render: (value) => <Tag color="blue">{value || '—'}</Tag> },
    { title: 'Talk time', dataIndex: 'talk_time', key: 'talk_time', render: (value) => `${Math.floor(value / 60)}m ${value % 60}s` },
    { title: 'Received', dataIndex: 'received_at', key: 'received_at', render: (value) => dayjs(value).format('DD MMM, h:mm A') },
    { title: 'Options', key: 'options', width: 88, align: 'center', render: (_, row) => (
      <Tooltip title={recordingTooltip(row)}><span><Button type="text" shape="circle" icon={<PlayCircleOutlined />} disabled={!row.recording_available} onClick={() => setSelectedCall(row)} aria-label={row.recording_available ? `Play recording for lead ${row.lead_id || row.id}` : recordingTooltip(row)} /></span></Tooltip>
    ) },
  ];

  const reload = () => { pageCache.current.clear(); setLoading(true); setError(''); void load(undefined, true); };
  const changeFilters = (nextFilters: CallLibraryFilterValue) => { setLoading(true); setFilters(nextFilters); setCurrentPage(1); setError(''); };
  const resetFilters = () => { setLoading(true); setFilters(DEFAULT_FILTERS); setCurrentPage(1); setError(''); };

  return (
    <div className="page-stack">
      <div className="page-heading"><div><Title level={2} className="page-title">Call library</Title><Paragraph className="page-subtitle">Explore every dialer call available to your branch.</Paragraph></div></div>
      <Card className="call-filter-card" classNames={{ body: 'call-filter-card__body' }}>
        <CallLibraryFilters value={filters} options={options} optionsLoading={optionsLoading} loading={loading} onChange={changeFilters} onReset={resetFilters} onRefresh={reload} />
      </Card>
      {error && <Alert type="error" showIcon title="Unable to filter calls" description={error} action={<Button onClick={reload}>Try again</Button>} />}
      <Card className="content-card" classNames={{ body: 'content-card__body' }} title={<span>Library results <Tag>{total}</Tag></span>} extra={<div className="page-capacity"><Progress type="circle" size={48} percent={Math.round((calls.length / pageSize) * 100)} strokeWidth={9} format={() => `${calls.length}/${pageSize}`} /><span><strong>Page capacity</strong><small>{pageSize} records selected</small></span></div>}>
        <Table className="content-table" rowKey="id" columns={columns} dataSource={calls} loading={{ spinning: loading, indicator: <PortalLoader compact label="Loading calls…" /> }} scroll={{ x: 1080 }} pagination={{ current: currentPage, pageSize, total, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100], showTotal: (recordCount, range) => `${range[0]}–${range[1]} of ${recordCount} records`, onChange: (page, nextPageSize) => { setLoading(true); setError(''); if (nextPageSize !== pageSize) { setPageSize(nextPageSize); setCurrentPage(1); return; } setCurrentPage(page); }, position: ['bottomRight'] }} locale={{ emptyText: <div className="empty-table"><CustomerServiceOutlined className="empty-table__icon" /><strong>No matching calls</strong><span>Adjust or clear filters to expand the result set.</span></div> }} />
      </Card>
      <AudioPlayerModal call={selectedCall} onClose={() => setSelectedCall(null)} />
    </div>
  );
}
