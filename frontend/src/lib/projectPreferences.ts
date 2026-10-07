export interface ProjectSelection {
  dialer: string;
  project: string;
}

export interface ProjectGroup {
  dialer_id: string;
  dialer_name: string;
  projects: string[];
}

export type ProjectUsage = Record<string, number>;
type PreferenceStorage = Pick<Storage, 'getItem' | 'setItem'>;

export function projectKey(selection: ProjectSelection) {
  return JSON.stringify([selection.dialer, selection.project]);
}

export function readProjectUsage(storage: PreferenceStorage, key: string): ProjectUsage {
  try {
    const raw = storage.getItem(key);
    if (!raw || raw.length > 50_000) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    return Object.fromEntries(Object.entries(parsed)
      .filter(([id, count]) => id.length < 500 && typeof count === 'number' && Number.isSafeInteger(count) && count > 0)
      .slice(0, 200));
  } catch {
    return {};
  }
}

export function recordProjectUsage(usage: ProjectUsage, selection: ProjectSelection, groups: ProjectGroup[]): ProjectUsage {
  const allowed = new Set(groups.flatMap((group) => group.projects.map((project) => projectKey({ dialer: group.dialer_id, project }))));
  const id = projectKey(selection);
  if (!allowed.has(id)) return usage;
  const next = Object.fromEntries(Object.entries(usage).filter(([key]) => allowed.has(key)));
  next[id] = Math.min((next[id] ?? 0) + 1, Number.MAX_SAFE_INTEGER);
  return Object.fromEntries(Object.entries(next).sort((a, b) => b[1] - a[1]).slice(0, 200));
}

export function saveProjectUsage(storage: PreferenceStorage, key: string, usage: ProjectUsage) {
  try { storage.setItem(key, JSON.stringify(usage)); } catch { /* Filtering still works when storage is blocked or full. */ }
}

export function rankProjectGroups(groups: ProjectGroup[], usage: ProjectUsage): ProjectGroup[] {
  const frequency = (dialer: string, project: string) => usage[projectKey({ dialer, project })] ?? 0;
  const groupFrequency = (group: ProjectGroup) => group.projects.reduce((sum, project) => sum + frequency(group.dialer_id, project), 0);
  return groups.map((group) => ({
    ...group,
    projects: [...group.projects].sort((a, b) => frequency(group.dialer_id, b) - frequency(group.dialer_id, a) || a.localeCompare(b)),
  })).sort((a, b) => groupFrequency(b) - groupFrequency(a) || a.dialer_name.localeCompare(b.dialer_name) || a.dialer_id.localeCompare(b.dialer_id));
}
