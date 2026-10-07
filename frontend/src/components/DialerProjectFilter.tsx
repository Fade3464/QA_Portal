import { ApiOutlined } from '@ant-design/icons';
import { TreeSelect } from 'antd';
import { useMemo, useState } from 'react';
import { projectKey, rankProjectGroups, readProjectUsage, recordProjectUsage, saveProjectUsage, type ProjectGroup, type ProjectSelection, type ProjectUsage } from '../lib/projectPreferences';

interface Props {
  groups: ProjectGroup[];
  value: ProjectSelection | undefined;
  onChange: (selection: ProjectSelection | undefined) => void;
  storageKey: string;
  placeholder: string;
  loading: boolean;
}

export function DialerProjectFilter({ groups, value, onChange, storageKey, placeholder, loading }: Props) {
  const [usage, setUsage] = useState<ProjectUsage>(() => {
    try { return readProjectUsage(window.localStorage, storageKey); } catch { return {}; }
  });
  const choices = useMemo(() => new Map(groups.flatMap((group) => group.projects.map((project) => {
    const selection = { dialer: group.dialer_id, project };
    return [projectKey(selection), selection] as const;
  }))), [groups]);
  const treeData = useMemo(() => rankProjectGroups(groups, usage).map((group) => ({
    key: `dialer:${group.dialer_id}`,
    value: `dialer:${group.dialer_id}`,
    title: <span className="pm-project-dialer"><ApiOutlined /><span>{group.dialer_name}</span></span>,
    selectable: false,
    searchText: group.dialer_name,
    children: group.projects.map((project) => ({
      key: projectKey({ dialer: group.dialer_id, project }),
      value: projectKey({ dialer: group.dialer_id, project }),
      title: project,
      label: `${project} · ${group.dialer_name}`,
      searchText: `${project} ${group.dialer_name}`,
    })),
  })), [groups, usage]);

  return <TreeSelect<string | undefined>
    className="pm-project-select"
    aria-label="Filter by dialer project"
    placeholder={placeholder}
    value={value ? projectKey(value) : undefined}
    treeData={treeData}
    treeNodeLabelProp="label"
    treeExpandAction="click"
    showSearch={{ treeNodeFilterProp: 'searchText' }}
    allowClear
    loading={loading}
    disabled={loading && !groups.length}
    listHeight={340}
    notFoundContent="No matching projects"
    onChange={(key) => onChange(key ? choices.get(key) : undefined)}
    onSelect={(key) => {
      const selection = key ? choices.get(key) : undefined;
      if (!selection) return;
      const next = recordProjectUsage(usage, selection, groups);
      setUsage(next);
      try { saveProjectUsage(window.localStorage, storageKey, next); } catch { /* Local storage can be disabled. */ }
    }}
  />;
}
