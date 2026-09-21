import { SearchOutlined } from '@ant-design/icons';
import { Button, Empty, Input, Popover, Select, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { DEFAULT_TEAM_AVATAR, TEAM_AVATARS } from '../data/teamAvatars';
import { MaterialSymbol } from './MaterialSymbol';

const { Text } = Typography;
const categories = ['All', ...new Set(TEAM_AVATARS.map((avatar) => avatar.category))];

export function TeamAvatarPicker({ value, onChange }: { value?: string; onChange?: (value: string) => void }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('All');
  const selected = TEAM_AVATARS.find((avatar) => avatar.value === value) ?? TEAM_AVATARS[0];
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return TEAM_AVATARS.filter((avatar) =>
      (category === 'All' || avatar.category === category)
      && (!needle || `${avatar.label} ${avatar.category}`.toLowerCase().includes(needle)),
    );
  }, [category, query]);

  const content = (
    <div className="team-avatar-picker__panel">
      <Input allowClear prefix={<SearchOutlined />} placeholder="Search symbols" value={query} onChange={(event) => setQuery(event.target.value)} />
      <Select
        value={category}
        onChange={setCategory}
        options={categories.map((item) => ({ value: item, label: item }))}
        aria-label="Avatar category"
        className="team-avatar-picker__categories"
      />
      <div className="team-avatar-picker__grid" role="listbox" aria-label="Team avatars">
        {filtered.map((avatar) => (
          <button
            type="button"
            key={avatar.value}
            className={`team-avatar-option${selected.value === avatar.value ? ' team-avatar-option--selected' : ''}`}
            aria-label={avatar.label}
            aria-selected={selected.value === avatar.value}
            role="option"
            onClick={() => { onChange?.(avatar.value); setOpen(false); }}
          >
            <MaterialSymbol name={avatar.value} />
            <span>{avatar.label}</span>
          </button>
        ))}
        {!filtered.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No matching symbols" />}
      </div>
      <Text type="secondary">{filtered.length} symbols</Text>
    </div>
  );

  return (
    <Popover open={open} onOpenChange={setOpen} trigger="click" placement="bottomLeft" content={content} destroyOnHidden rootClassName="team-avatar-picker__popover">
      <Button className="team-avatar-picker__trigger">
        <span className="team-avatar team-avatar--preview"><MaterialSymbol name={selected?.value ?? DEFAULT_TEAM_AVATAR} /></span>
        <span><strong>{selected?.label ?? 'Choose avatar'}</strong></span>
      </Button>
    </Popover>
  );
}
