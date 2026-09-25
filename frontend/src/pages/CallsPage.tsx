import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  CustomerServiceOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { RiArrowDownLongLine, RiArrowRightUpLongLine, RiFlagFill, RiPhoneFill } from '@remixicon/react';
import { Alert, Button, Card, FloatButton, Table, Tooltip, Typography, type TableProps } from 'antd';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { AudioPlayerModal } from '../components/AudioPlayerModal';
import { AnalysisWorkspaceModal } from '../components/AnalysisWorkspaceModal';
import { CallLibraryFilters, type CallLibraryFilterValue } from '../components/CallLibraryFilters';
import { TableSkeleton } from '../components/LoadingStates';
import { MaterialSymbol } from '../components/MaterialSymbol';
import { api } from '../lib/api';
import { appDate } from '../lib/datetime';
import { useAuth } from '../auth/AuthContext';
import { useThemeSettings } from '../theme/ThemeContext';
import type { CallEvent, CallFilterOptions, CallReservation, PaginatedResponse, QAAnalysisResponse } from '../types';

const { Title } = Typography;
const PAGE_CACHE_TTL_MS = 30_000;
const PAGE_CACHE_LIMIT = 20;
const COLUMN_SORT_FIELDS: Record<string, string> = {
  lead_id: 'lead_id', agent: 'agent_name',
  project_name: 'project_name', phone_number: 'phone_number', disposition: 'disposition',
  talk_time: 'talk_time', received_at: 'received_at',
};

const DEFAULT_ORDERING = '-received_at';

function defaultFilters(): CallLibraryFilterValue {
  const today = appDate();
  return {
    search: '', agents: [], teams: [], projects: [], dispositions: [], terminationReasons: [], dialers: [], eventTypes: [], recordingStatuses: [],
    dateField: 'received_at', dateFrom: today.startOf('day').toISOString(), dateTo: today.endOf('day').toISOString(), relativeRange: 'today',
    talkTimeMin: undefined, talkTimeMax: undefined, ordering: DEFAULT_ORDERING,
  };
}

type CachedCallPage = { cachedAt: number; response: PaginatedResponse<CallEvent> };

function CallDirectionIcon({ call }: { call: CallEvent }) {
  const { call_direction: direction, dial_method: dialMethod } = call;
  if (direction === 'INBOUND') {
    return <RiArrowDownLongLine className="library-direction library-direction--inbound" aria-label="Inbound call" />;
  }
  if (direction === 'OUTBOUND') {
    if (dialMethod === 'MANUAL') {
      return <span className="library-direction library-direction--manual" aria-label="Manually dialed call">M</span>;
    }
    return <RiArrowRightUpLongLine className="library-direction library-direction--outbound" aria-label="Outbound call" />;
  }
  return null;
}

function PhoneNumberCell({ call }: { call: CallEvent }) {
  const content = <span className="library-phone-cell"><span className="library-phone">{call.phone_number || '—'}</span><CallDirectionIcon call={call} /></span>;
  if (call.call_direction !== 'INBOUND') return content;
  return <Tooltip title={call.group ? `In-group: ${call.group}` : 'In-group unavailable'} mouseEnterDelay={0.35}>{content}</Tooltip>;
}

function AgentCell({ call }: { call: CallEvent }) {
  const name = call.agent_name || call.agent_user || '—';
  const tooltip = `${call.team_name || 'Unassigned'} · ${call.agent_user || 'ID unavailable'}`;
  return (
    <Tooltip title={tooltip} mouseEnterDelay={0.35}>
      <span className="library-agent-cell">
        <span className="library-agent">{name}</span>
        {call.team_avatar && <span className="team-avatar team-avatar--agent"><MaterialSymbol name={call.team_avatar} /></span>}
      </span>
    </Tooltip>
  );
}

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
  const defaults = defaultFilters();
  const hasTimeFilter = params.has('date_from') || params.has('date_to') || params.has('time_range');
  return {
    search: params.get('search') ?? '',
    agents: listParameter(params, 'agent'), teams: listParameter(params, 'team'), projects: listParameter(params, 'project'),
    dispositions: listParameter(params, 'disposition'), terminationReasons: listParameter(params, 'termination_reason'), dialers: listParameter(params, 'dialer'),
    eventTypes: listParameter(params, 'event_type'), recordingStatuses: listParameter(params, 'recording_status'),
    dateField: params.get('date_field') === 'call_date' ? 'call_date' : 'received_at',
    dateFrom: hasTimeFilter ? params.get('date_from') ?? '' : defaults.dateFrom,
    dateTo: params.get('date_to') ?? '', relativeRange: hasTimeFilter ? params.get('time_range') ?? '' : defaults.relativeRange,
    talkTimeMin: numberParameter(params, 'talk_time_min'), talkTimeMax: numberParameter(params, 'talk_time_max'),
    ordering: params.get('ordering') ?? DEFAULT_ORDERING,
  };
}

function filterQuery(filters: CallLibraryFilterValue) {
  const query = new URLSearchParams();
  const values: Array<[string, string | number | undefined]> = [
    ['search', filters.search.trim()],
    ['date_field', filters.dateField === 'received_at' ? '' : filters.dateField], ['date_from', filters.dateFrom],
    ['date_to', filters.dateTo], ['time_range', filters.relativeRange], ['talk_time_min', filters.talkTimeMin], ['talk_time_max', filters.talkTimeMax],
    ['ordering', filters.ordering === DEFAULT_ORDERING ? '' : filters.ordering],
  ];
  values.forEach(([name, value]) => { if (value !== '' && value !== undefined) query.set(name, String(value)); });
  const multipleValues: Array<[string, string[]]> = [
    ['agent', filters.agents], ['team', filters.teams], ['project', filters.projects], ['disposition', filters.dispositions],
    ['termination_reason', filters.terminationReasons],
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
  const { user } = useAuth();
  const { compact } = useThemeSettings();
  const [searchParams, setSearchParams] = useSearchParams();
  const isQa = user?.role === 'qa' && !user.is_superuser;
  const [calls, setCalls] = useState<CallEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [currentPage, setCurrentPage] = useState(() => Math.max(1, Number(searchParams.get('page')) || 1));
  const [pageSize, setPageSize] = useState(() => [10, 20, 50, 100].includes(Number(searchParams.get('page_size'))) ? Number(searchParams.get('page_size')) : 20);
  const [total, setTotal] = useState(0);
  const [selectedCall, setSelectedCall] = useState<CallEvent | null>(null);
  const [analysisCall, setAnalysisCall] = useState<CallEvent | null>(null);
  const [analysisTarget, setAnalysisTarget] = useState(() => searchParams.get('analysis'));
  const [analysisOpenError, setAnalysisOpenError] = useState('');
  const [filters, setFilters] = useState(() => {
    const parsed = filtersFromParams(searchParams);
    return isQa ? { ...parsed, dialers: [], eventTypes: [] } : parsed;
  });
  const [options, setOptions] = useState<CallFilterOptions | null>(null);
  const [optionsLoading, setOptionsLoading] = useState(true);
  const pageCache = useRef(new Map<string, CachedCallPage>());
  const serializedFilters = useMemo(() => filterQuery(filters).toString(), [filters]);

  const updateReservation = useCallback((callId: string, reservation: CallReservation | null) => {
    const normalize = (value: CallReservation | null) => value
      ? { ...value, is_mine: value.reviewer_id === user?.id }
      : null;
    const nextReservation = normalize(reservation);
    setCalls((current) => current.map((item) => item.id === callId ? { ...item, reservation: nextReservation } : item));
    pageCache.current.clear();
  }, [user?.id]);

  useEffect(() => {
    const handleReservation = (event: Event) => {
      const detail = (event as CustomEvent<{ call_id?: string; reservation?: CallReservation | null }>).detail;
      if (detail.call_id) updateReservation(detail.call_id, detail.reservation ?? null);
    };
    window.addEventListener('qa:call-reservation', handleReservation);
    return () => window.removeEventListener('qa:call-reservation', handleReservation);
  }, [updateReservation]);

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
    if (analysisTarget) params.set('analysis', analysisTarget);
    setSearchParams(params, { replace: true });
  }, [analysisTarget, currentPage, pageSize, serializedFilters, setSearchParams]);

  useEffect(() => {
    if (!analysisTarget || !isQa) return;
    const controller = new AbortController();
    api<QAAnalysisResponse>(`/api/v1/calls/${encodeURIComponent(analysisTarget)}/analysis/`, { signal: controller.signal })
      .then((result) => {
        setAnalysisOpenError('');
        setAnalysisCall(result.call);
        updateReservation(result.call.id, result.call.reservation);
      })
      .catch((requestError: unknown) => {
        if (requestError instanceof DOMException && requestError.name === 'AbortError') return;
        setAnalysisOpenError(requestError instanceof Error ? requestError.message : 'This QA report could not be reopened.');
      })
      .finally(() => { if (!controller.signal.aborted) setAnalysisTarget(null); });
    return () => controller.abort();
  }, [analysisTarget, isQa, updateReservation]);

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
    { title: 'Phone number', dataIndex: 'phone_number', key: 'phone_number', width: 175, render: (_, row) => <PhoneNumberCell call={row} /> },
    { title: 'Agent', key: 'agent', width: 205, render: (_, row) => <AgentCell call={row} /> },
    { title: 'Project', dataIndex: 'project_name', key: 'project_name', width: 145, render: (value) => <span className="library-secondary library-wrap">{value || 'Unmapped'}</span> },
    { title: 'Disposition', dataIndex: 'disposition', key: 'disposition', width: 125, render: (value) => <span className="library-disposition">{value || '—'}</span> },
    { title: 'Talk time', dataIndex: 'talk_time', key: 'talk_time', width: 125, align: 'right', render: (value, row) => {
      const terminationReason = row.termination_reason?.trim().toUpperCase() ?? '';
      return <span className="library-talk-time"><span className="library-duration">{Math.floor(value / 60)}<small>m </small>{value % 60}<small>s</small></span>{terminationReason === 'AGENT' ? <RiFlagFill className="library-termination library-termination--agent" aria-label="Agent terminated the call" /> : terminationReason === 'CALLER' ? <span className="library-termination library-termination--caller" role="img" aria-label="Caller terminated the call"><RiPhoneFill /></span> : null}</span>;
    } },
    { title: 'Received', dataIndex: 'received_at', key: 'received_at', width: 145, render: (value) => <Tooltip title={`${appDate(value).format('DD MMM YYYY, h:mm:ss A')} ET`}><span className="library-date">{appDate(value).format('DD MMM YYYY')}<small>{appDate(value).format('h:mm A')} ET</small></span></Tooltip> },
    { title: 'Options', key: 'options', width: 84, fixed: 'right', align: 'center', render: (_, row) => {
      if (isQa) {
        const lockedByAnother = Boolean(row.reservation && !row.reservation.is_mine);
        const enabled = row.recording_available && !lockedByAnother;
        const tooltip = !row.recording_available ? recordingTooltip(row) : lockedByAnother ? `Reserved by ${row.reservation?.reviewer_name}` : row.reservation?.is_mine ? 'Continue analysis' : 'Analyze';
        return <Tooltip title={tooltip}><span className="library-play-target" tabIndex={enabled ? undefined : 0} aria-label={enabled ? undefined : tooltip}><Button className={`library-play${enabled ? ' library-play--ready' : ''}`} type="text" shape="circle" icon={<SearchOutlined />} disabled={!enabled} onClick={() => setAnalysisCall(row)} aria-label={tooltip} /></span></Tooltip>;
      }
      return <Tooltip title={recordingTooltip(row)}><span className="library-play-target" tabIndex={row.recording_available ? undefined : 0} aria-label={row.recording_available ? undefined : recordingTooltip(row)}><Button className={`library-play${row.recording_available ? ' library-play--ready' : ''}`} type="text" shape="circle" icon={<PlayCircleOutlined />} disabled={!row.recording_available} onClick={() => setSelectedCall(row)} aria-label={row.recording_available ? `Play recording for lead ${row.lead_id || row.id}` : recordingTooltip(row)} /></span></Tooltip>;
    } },
  ];

  const reload = () => { pageCache.current.clear(); setLoading(true); setError(''); void load(undefined, true); };
  const changeFilters = (nextFilters: CallLibraryFilterValue) => { setLoading(true); setFilters(nextFilters); setCurrentPage(1); setError(''); };
  const resetFilters = () => { setLoading(true); setFilters(defaultFilters()); setCurrentPage(1); setError(''); };
  const sortableColumns: TableProps<CallEvent>['columns'] = columns.map((column) => {
    const field = COLUMN_SORT_FIELDS[String(column.key)];
    if (!field) return { ...column, align: 'center' };
    return {
      ...column,
      align: 'center',
      sorter: true,
      sortDirections: ['ascend', 'descend', 'ascend'],
      onHeaderCell: () => ({ style: { color: 'var(--qa-text-muted)' } }),
      sortIcon: ({ sortOrder }) => sortOrder ? <span className="library-sort" aria-hidden="true">{sortOrder === 'ascend' ? <ArrowUpOutlined /> : <ArrowDownOutlined />}</span> : null,
      sortOrder: filters.ordering === field ? 'ascend' : filters.ordering === `-${field}` ? 'descend' : null,
    };
  });
  const handleTableChange: TableProps<CallEvent>['onChange'] = (pagination, _tableFilters, sorter, extra) => {
    if (extra.action === 'sort') {
      const selectedSort = Array.isArray(sorter) ? sorter[0] : sorter;
      const field = COLUMN_SORT_FIELDS[String(selectedSort?.columnKey)];
      const ordering = field && selectedSort.order
        ? `${selectedSort.order === 'descend' ? '-' : ''}${field}`
        : DEFAULT_ORDERING;
      if (ordering === filters.ordering && currentPage === 1) return;
      changeFilters({ ...filters, ordering });
    } else if (extra.action === 'paginate') {
      const nextPageSize = pagination.pageSize ?? pageSize;
      setLoading(true);
      setError('');
      setPageSize(nextPageSize);
      setCurrentPage(nextPageSize !== pageSize ? 1 : pagination.current ?? 1);
    }
  };

  return (
    <>
    <div className="page-stack">
      <div className="page-heading"><div><Title level={2} className="page-title">{isQa ? 'Calls for review' : 'Call library'}</Title></div></div>
      {analysisOpenError && <Alert type="error" showIcon closable={{ onClose: () => setAnalysisOpenError('') }} title="Unable to continue analysis" description={analysisOpenError} />}
      <Card className="call-filter-card" classNames={{ body: 'call-filter-card__body' }}>
        <CallLibraryFilters simplified={isQa} value={filters} options={options} optionsLoading={optionsLoading} loading={loading} onChange={changeFilters} onReset={resetFilters} onRefresh={reload} />
      </Card>
      {error && <Alert type="error" showIcon title="Unable to filter calls" description={error} action={<Button icon={<ReloadOutlined />} onClick={reload}>Try again</Button>} />}
      <Card className="library-card" classNames={{ header: 'library-card__header', body: 'content-card__body' }} title={<div className="library-card__heading"><span>Call records <span className="library-count">{total.toLocaleString()}</span></span></div>}>
        {loading ? <TableSkeleton rows={Math.min(pageSize, 8)} columns={7} /> : <Table<CallEvent>
          className="library-table"
          classNames={{ header: { cell: 'library-table__heading' }, body: { cell: 'library-table__cell' }, pagination: { root: 'library-table__pagination' } }}
          size={compact ? 'small' : 'middle'}
          rowKey="id" columns={sortableColumns} onChange={handleTableChange} dataSource={calls}
          showSorterTooltip={false}
          scroll={{ x: 1004 }}
          pagination={{ current: currentPage, pageSize, total, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100], showTotal: (recordCount, range) => `${range[0]}–${range[1]} of ${recordCount.toLocaleString()} calls`, position: ['bottomRight'] }}
          locale={{ emptyText: <div className="empty-table"><CustomerServiceOutlined className="empty-table__icon" /><strong>No matching calls</strong></div> }}
        />}
      </Card>
      <AudioPlayerModal call={selectedCall} onClose={() => setSelectedCall(null)} />
      {analysisCall && <AnalysisWorkspaceModal call={analysisCall} onClose={() => setAnalysisCall(null)} onReservationChange={updateReservation} />}
    </div>
    {/* Keep fixed positioning outside the animated page-stack children. */}
    <FloatButton.BackTop
      showProgress
      visibilityHeight={80}
      duration={450}
      tooltip="Back to top"
      aria-label="Scroll back to top"
      style={{ insetInlineEnd: 24, insetBlockEnd: 24 }}
    />
    </>
  );
}
