import { ApiOutlined } from '@ant-design/icons';
import { TreeSelect } from 'antd';
import { useMemo, useState } from 'react';
import { projectKey, rankProjectGroups, readProjectUsage, recordProjectUsage, saveProjectUsage, type ProjectGroup, type ProjectSelection, type ProjectUsage } from '../lib/projectPreferences';

interface Props {
  groups: ProjectGroup[];
  value: ProjectSelection[];
  onChange: (selection: ProjectSelection[]) => void;
  storageKey: string;
  placeholder: string;
  loading: boolean;
}

export function DialerProjectFilter({ groups, value, onChange, storageKey, placeholder, loading }: Props) {
  const [usage, setUsage] = useState<ProjectUsage>(() => {
    try { return readProjectUsage(window.localStorage, storageKey); } catch { return {}; }
  });
  const [searchValue, setSearchValue] = useState('');
  const [expandedKeys, setExpandedKeys] = useState<string[]>([]);
  const [open, setOpen] = useState(false);
  const [openUsage, setOpenUsage] = useState(usage);
  const choices = useMemo(() => new Map(groups.flatMap((group) => group.projects.map((project) => {
    const selection = { dialer: group.dialer_id, project };
    return [projectKey(selection), selection] as const;
  }))), [groups]);
  const treeData = useMemo(() => rankProjectGroups(groups, open ? openUsage : usage).map((group) => ({
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
  })), [groups, usage, open, openUsage]);

  return <TreeSelect<string[]>
    className="pm-project-select"
    aria-label="Filter by dialer projects"
    placeholder={!loading && !groups.length ? 'No accessible projects' : placeholder}
    value={value.map(projectKey)}
    treeCheckable
    showCheckedStrategy={TreeSelect.SHOW_CHILD}
    maxCount={200}
    maxTagCount="responsive"
    maxTagTextLength={30}
    maxTagPlaceholder={(omitted) => `+${omitted.length} projects`}
    onOpenChange={(nextOpen) => {
      if (nextOpen) { setOpenUsage(usage); setExpandedKeys(groups.map((group) => `dialer:${group.dialer_id}`)); }
      else setSearchValue('');
      setOpen(nextOpen);
    }}
    onClear={() => setSearchValue('')}
    treeData={treeData}
    treeNodeLabelProp="label"
    treeExpandAction="click"
    treeExpandedKeys={expandedKeys}
    onTreeExpand={(keys) => setExpandedKeys(keys.map(String))}
    popupRender={(content) => <>{content}<div className="pm-project-popup-help">Select up to 200 projects across dialers. Clear to include all.</div></>}
    showSearch={{ treeNodeFilterProp: 'searchText', searchValue, onSearch: (next) => { setSearchValue(next); if (next) setExpandedKeys(groups.map((group) => `dialer:${group.dialer_id}`)); }, autoClearSearchValue: false }}
    allowClear
    loading={loading}
    disabled={!groups.length}
    listHeight={340}
    notFoundContent="No matching projects"
    onChange={(keys) => {
      const selected = keys.flatMap((key) => {
        const selection = choices.get(key);
        return selection ? [selection] : [];
      });
      const previous = new Set(value.map(projectKey));
      let next = usage;
      for (const selection of selected) {
        if (!previous.has(projectKey(selection))) next = recordProjectUsage(next, selection, groups);
      }
      if (next !== usage) {
        setUsage(next);
        try { saveProjectUsage(window.localStorage, storageKey, next); } catch { /* Storage may be disabled. */ }
      }
      onChange(selected);
    }}
  />;
}
