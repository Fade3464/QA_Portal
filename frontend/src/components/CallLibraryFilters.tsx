import {
  ClockCircleOutlined,
  FilterOutlined,
  ReloadOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import {
  Badge,
  Button,
  DatePicker,
  Divider,
  Drawer,
  Input,
  InputNumber,
  Select,
  Tag,
  Typography,
} from 'antd';
import { useState } from 'react';
import { appDate, appWallTimeToIso } from '../lib/datetime';
import type { CallFilterOptions } from '../types';

const { Text, Title } = Typography;
const { RangePicker } = DatePicker;

export interface CallLibraryFilterValue {
  search: string;
  agents: string[];
  teams: string[];
  projects: string[];
  dispositions: string[];
  terminationReasons: string[];
  dialers: string[];
  eventTypes: string[];
  recordingStatuses: string[];
  dateField: 'received_at' | 'call_date';
  dateFrom: string;
  dateTo: string;
  relativeRange: string;
  talkTimeMin?: number;
  talkTimeMax?: number;
  ordering: string;
}

interface CallLibraryFiltersProps {
  value: CallLibraryFilterValue;
  options: CallFilterOptions | null;
  optionsLoading: boolean;
  loading: boolean;
  onChange: (value: CallLibraryFilterValue) => void;
  onReset: () => void;
  onRefresh: () => void;
  simplified?: boolean;
}

const TIME_RANGES = [
  { value: '15m', label: 'Last 15 minutes', amount: 15, unit: 'minute' },
  { value: '1h', label: 'Last 1 hour', amount: 1, unit: 'hour' },
  { value: '6h', label: 'Last 6 hours', amount: 6, unit: 'hour' },
  { value: '24h', label: 'Last 24 hours', amount: 24, unit: 'hour' },
  { value: '7d', label: 'Last 7 days', amount: 7, unit: 'day' },
  { value: '30d', label: 'Last 30 days', amount: 30, unit: 'day' },
] as const;

function selectedTimeRange(value: CallLibraryFilterValue) {
  if (!value.dateFrom && !value.dateTo) return 'all';
  return value.relativeRange || 'custom';
}

function optionList(values: string[] | undefined) {
  return (values ?? []).map((value) => ({ value, label: value }));
}

export function CallLibraryFilters({
  value,
  options,
  optionsLoading,
  loading,
  onChange,
  onReset,
  onRefresh,
  simplified = false,
}: CallLibraryFiltersProps) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const patch = (change: Partial<CallLibraryFilterValue>) => onChange({ ...value, ...change });
  const activeCount = [
    value.search,
    value.agents.length,
    value.teams.length,
    value.projects.length,
    value.dispositions.length,
    value.terminationReasons.length,
    simplified ? 0 : value.dialers.length,
    simplified ? 0 : value.eventTypes.length,
    value.recordingStatuses.length,
    value.dateFrom || value.dateTo,
    value.talkTimeMin !== undefined || value.talkTimeMax !== undefined,
    value.ordering !== '-received_at',
  ].filter(Boolean).length;

  const setTimeRange = (range: string) => {
    if (range === 'all') {
      patch({ dateFrom: '', dateTo: '', relativeRange: '' });
      return;
    }
    if (range === 'custom') {
      setDrawerOpen(true);
      return;
    }
    const preset = TIME_RANGES.find((item) => item.value === range);
    if (!preset) return;
    patch({
      dateFrom: appDate().subtract(preset.amount, preset.unit).toISOString(),
      dateTo: '',
      dateField: 'received_at',
      relativeRange: range,
    });
  };

  const chips = [
    value.agents.length ? { key: 'agents', label: `Agent: ${value.agents.join(', ')}`, clear: () => patch({ agents: [] }) } : null,
    value.teams.length ? { key: 'teams', label: `Team: ${value.teams.join(', ')}`, clear: () => patch({ teams: [] }) } : null,
    value.projects.length ? { key: 'projects', label: `Project: ${value.projects.join(', ')}`, clear: () => patch({ projects: [] }) } : null,
    value.dispositions.length ? { key: 'dispositions', label: `Disposition: ${value.dispositions.join(', ')}`, clear: () => patch({ dispositions: [] }) } : null,
    value.terminationReasons.length ? { key: 'termination-reasons', label: `Termination: ${value.terminationReasons.join(', ')}`, clear: () => patch({ terminationReasons: [] }) } : null,
    !simplified && value.dialers.length ? { key: 'dialers', label: `Dialer: ${value.dialers.join(', ')}`, clear: () => patch({ dialers: [] }) } : null,
    !simplified && value.eventTypes.length ? { key: 'events', label: `Event: ${value.eventTypes.join(', ')}`, clear: () => patch({ eventTypes: [] }) } : null,
    value.recordingStatuses.length ? { key: 'recordings', label: `Recording: ${value.recordingStatuses.join(', ')}`, clear: () => patch({ recordingStatuses: [] }) } : null,
    value.dateFrom || value.dateTo ? { key: 'time', label: `Time: ${selectedTimeRange(value) === 'custom' ? 'custom range' : TIME_RANGES.find((item) => item.value === selectedTimeRange(value))?.label ?? 'selected'}`, clear: () => patch({ dateFrom: '', dateTo: '', relativeRange: '' }) } : null,
    value.talkTimeMin !== undefined || value.talkTimeMax !== undefined
      ? { key: 'duration', label: `Talk time: ${value.talkTimeMin ?? 0}s–${value.talkTimeMax ?? '∞'}s`, clear: () => patch({ talkTimeMin: undefined, talkTimeMax: undefined }) }
      : null,
  ].filter((chip): chip is NonNullable<typeof chip> => Boolean(chip));

  return (
    <div className="call-filters">
      <div className="call-filters__toolbar">
        <Input
          className="call-filters__search"
          value={value.search}
          onChange={(event) => patch({ search: event.target.value })}
          prefix={<SearchOutlined />}
          placeholder={simplified ? 'Search phone, agent, team or project…' : 'Search phone, lead, agent, project, call ID…'}
          allowClear
          maxLength={200}
          aria-label="Search calls"
        />
        <Select
          className="call-filters__time"
          value={selectedTimeRange(value)}
          onChange={setTimeRange}
          prefix={<ClockCircleOutlined />}
          options={[
            ...TIME_RANGES.map(({ value: rangeValue, label }) => ({ value: rangeValue, label })),
            { value: 'all', label: 'All time' },
            { value: 'custom', label: 'Custom range' },
          ]}
          aria-label="Time range"
        />
        <Badge count={activeCount} size="small" offset={[-2, 2]}>
          <Button icon={<FilterOutlined />} onClick={() => setDrawerOpen(true)}>Filters</Button>
        </Badge>
        {activeCount > 0 && <Button type="text" onClick={onReset}>Clear</Button>}
        <Button className="call-filters__refresh" icon={<ReloadOutlined />} loading={loading} onClick={onRefresh}>Refresh</Button>
      </div>

      {chips.length > 0 && (
        <div className="call-filters__chips" aria-label="Active filters">
          <Text type="secondary">Filtered by</Text>
          {chips.map((chip) => <Tag key={chip.key} closable onClose={chip.clear}>{chip.label}</Tag>)}
        </div>
      )}

      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        size={480}
        title={<div><Title level={4}>{simplified ? 'Filter QA calls' : 'Explore calls'}</Title><Text type="secondary">{simplified ? 'Narrow the calls available for evaluation.' : 'Combine filters to narrow the library.'}</Text></div>}
        extra={<Badge count={activeCount} showZero color="var(--qa-primary)" />}
        classNames={{ body: 'call-filter-drawer__body' }}
      >
        <div className="call-filter-form">
          <section>
            <Text strong>Time window</Text>
            <Text type="secondary">Filter by ingestion time or the dialer call timestamp.</Text>
            <Select
              value={value.dateField}
              onChange={(dateField) => patch({ dateField, relativeRange: 'custom' })}
              options={[{ value: 'received_at', label: 'Received at' }, { value: 'call_date', label: 'Call date' }]}
            />
            <RangePicker
              showTime
              value={value.dateFrom ? [appDate(value.dateFrom), value.dateTo ? appDate(value.dateTo) : appDate()] : null}
              onChange={(dates) => patch({
                dateFrom: dates?.[0] ? appWallTimeToIso(dates[0]) : '',
                dateTo: dates?.[1] ? appWallTimeToIso(dates[1]) : '',
                relativeRange: dates ? 'custom' : '',
              })}
              presets={TIME_RANGES.map((preset) => ({
                label: preset.label,
                value: [appDate().subtract(preset.amount, preset.unit), appDate()],
              }))}
            />
          </section>

          <Divider />
          <section>
            <Text strong>Call dimensions</Text>
            <Text type="secondary">Selections use OR within a field and AND across fields.</Text>
            <label>Agents<Select mode="multiple" allowClear showSearch maxTagCount="responsive" loading={optionsLoading} value={value.agents} options={optionList(options?.agents)} onChange={(agents) => patch({ agents })} placeholder="Any agent" /></label>
            <label>Teams<Select mode="multiple" allowClear showSearch maxTagCount="responsive" loading={optionsLoading} value={value.teams} options={optionList(options?.teams)} onChange={(teams) => patch({ teams })} placeholder="Any team" /></label>
            <label>Projects<Select mode="multiple" allowClear showSearch maxTagCount="responsive" loading={optionsLoading} value={value.projects} options={optionList(options?.projects)} onChange={(projects) => patch({ projects })} placeholder="Any project" /></label>
            <label>Dispositions<Select mode="multiple" allowClear showSearch maxTagCount="responsive" loading={optionsLoading} value={value.dispositions} options={optionList(options?.dispositions)} onChange={(dispositions) => patch({ dispositions })} placeholder="Any disposition" /></label>
            <label>Termination reasons<Select mode="multiple" allowClear showSearch maxTagCount="responsive" loading={optionsLoading} value={value.terminationReasons} options={optionList(options?.termination_reasons)} onChange={(terminationReasons) => patch({ terminationReasons })} placeholder="Any termination reason" /></label>
            {!simplified && <label>Dialers<Select mode="multiple" allowClear showSearch maxTagCount="responsive" loading={optionsLoading} value={value.dialers} options={optionList(options?.dialers)} onChange={(dialers) => patch({ dialers })} placeholder="Any dialer" /></label>}
            {!simplified && <label>Event types<Select mode="multiple" allowClear loading={optionsLoading} value={value.eventTypes} options={options?.event_types ?? []} onChange={(eventTypes) => patch({ eventTypes })} placeholder="Any event type" /></label>}
            <label>{simplified ? 'Recording readiness' : 'Recording states'}<Select mode="multiple" allowClear showSearch maxTagCount="responsive" loading={optionsLoading} value={value.recordingStatuses} options={options?.recording_statuses ?? []} onChange={(recordingStatuses) => patch({ recordingStatuses })} placeholder={simplified ? 'Any readiness state' : 'Any recording state'} /></label>
          </section>

          <Divider />
          <section>
            <Text strong>Talk time</Text>
            <Text type="secondary">Use seconds; either boundary can be left empty.</Text>
            <div className="call-filter-form__range">
              <label>Minimum<div className="call-filter-form__unit"><InputNumber min={0} precision={0} value={value.talkTimeMin} onChange={(talkTimeMin) => patch({ talkTimeMin: talkTimeMin ?? undefined })} placeholder="0" /><span>sec</span></div></label>
              <label>Maximum<div className="call-filter-form__unit"><InputNumber min={0} precision={0} value={value.talkTimeMax} onChange={(talkTimeMax) => patch({ talkTimeMax: talkTimeMax ?? undefined })} placeholder="No limit" /><span>sec</span></div></label>
            </div>
          </section>

          <Divider />
          <section>
            <Text strong>Sort results</Text>
            <Select
              value={value.ordering}
              onChange={(ordering) => patch({ ordering })}
              options={[
                { value: '-received_at', label: 'Newest received first' },
                { value: 'received_at', label: 'Oldest received first' },
                { value: '-call_date', label: 'Newest call first' },
                { value: 'call_date', label: 'Oldest call first' },
                { value: '-talk_time', label: 'Longest talk time first' },
                { value: 'talk_time', label: 'Shortest talk time first' },
                { value: 'agent_name', label: 'Agent A–Z' },
                { value: '-agent_name', label: 'Agent Z–A' },
                ...(!simplified ? [
                  { value: 'team_name', label: 'Team A–Z' },
                  { value: '-team_name', label: 'Team Z–A' },
                  { value: 'lead_id', label: 'Lead ID ascending' },
                  { value: '-lead_id', label: 'Lead ID descending' },
                ] : []),
                { value: 'phone_number', label: 'Phone number ascending' },
                { value: '-phone_number', label: 'Phone number descending' },
                { value: 'project_name', label: 'Project A–Z' },
                { value: '-project_name', label: 'Project Z–A' },
                { value: 'disposition', label: 'Disposition A–Z' },
                { value: '-disposition', label: 'Disposition Z–A' },
              ]}
            />
          </section>

          <div className="call-filter-form__actions">
            <Button onClick={onReset}>Reset all</Button>
            <Button type="primary" onClick={() => setDrawerOpen(false)}>View results</Button>
          </div>
        </div>
      </Drawer>
    </div>
  );
}
