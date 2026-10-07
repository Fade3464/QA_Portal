import assert from 'node:assert/strict';
import test from 'node:test';
import { projectKey, rankProjectGroups, readProjectUsage, recordProjectUsage, saveProjectUsage } from '../src/lib/projectPreferences.ts';

const groups = [
  { dialer_id: 'a', dialer_name: 'Alpha', projects: ['First', 'Shared'] },
  { dialer_id: 'b', dialer_name: 'Beta', projects: ['Other', 'Shared'] },
];

test('popular projects and their dialers rise without mutating the source', () => {
  const usage = { [projectKey({ dialer: 'b', project: 'Shared' })]: 5 };
  const ranked = rankProjectGroups(groups, usage);
  assert.equal(ranked[0].dialer_id, 'b');
  assert.deepEqual(ranked[0].projects, ['Shared', 'Other']);
  assert.equal(groups[0].dialer_id, 'a');
  assert.deepEqual(groups[1].projects, ['Other', 'Shared']);
});

test('same-named projects have independent usage and removed access is pruned', () => {
  const selected = { dialer: 'b', project: 'Shared' };
  const usage = recordProjectUsage({ stale: 7 }, selected, groups);
  assert.deepEqual(usage, { [projectKey(selected)]: 1 });
  assert.equal(usage[projectKey({ dialer: 'a', project: 'Shared' })], undefined);
  assert.equal(recordProjectUsage(usage, { dialer: 'hidden', project: 'Shared' }, groups), usage);
  assert.equal(recordProjectUsage(usage, selected, groups)[projectKey(selected)], 2);
});

test('preferences survive reload and remain isolated by account/branch key', () => {
  const data = new Map();
  const storage = { getItem: (key) => data.get(key) ?? null, setItem: (key, value) => data.set(key, value) };
  const usage = recordProjectUsage({}, { dialer: 'b', project: 'Shared' }, groups);
  saveProjectUsage(storage, 'user-1:branch-1', usage);
  assert.deepEqual(readProjectUsage(storage, 'user-1:branch-1'), usage);
  assert.deepEqual(readProjectUsage(storage, 'user-2:branch-1'), {});
  assert.deepEqual(readProjectUsage(storage, 'user-1:branch-2'), {});
});

test('corrupt, oversized, or unavailable storage does not break filtering', () => {
  for (const value of ['{', 'null', '[]', '"string"', 'x'.repeat(50_001)]) {
    assert.deepEqual(readProjectUsage({ getItem: () => value }, 'key'), {});
  }
  assert.deepEqual(readProjectUsage({ getItem: () => '{"ok":2,"bad":-2,"float":1.5,"text":"1"}' }, 'key'), { ok: 2 });
  const blocked = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('full'); } };
  assert.deepEqual(readProjectUsage(blocked, 'key'), {});
  assert.doesNotThrow(() => saveProjectUsage(blocked, 'key', {}));
});

test('unselected projects stay alphabetical and histories are bounded', () => {
  assert.deepEqual(rankProjectGroups([...groups].reverse(), {})[0], groups[0]);
  const oversized = Object.fromEntries(Array.from({ length: 300 }, (_, i) => [`id-${i}`, 1]));
  assert.equal(Object.keys(readProjectUsage({ getItem: () => JSON.stringify(oversized) }, 'key')).length, 200);
});
