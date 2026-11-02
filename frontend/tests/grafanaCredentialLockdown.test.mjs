import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

const nginx = readFileSync(new URL('../nginx.conf', import.meta.url), 'utf8');
const css = readFileSync(new URL('../public/grafana-lockdown.css', import.meta.url), 'utf8');

test('Grafana self-service password changes are blocked at the public proxy', () => {
  assert.match(nginx, /location = \/analytics\/profile\/password \{[\s\S]*?return 302 \/analytics\//);
  assert.match(nginx, /location = \/analytics\/api\/user\/password \{[\s\S]*?return 403/);
});

test('Grafana viewer password menu is hidden without patching the Grafana image', () => {
  assert.match(nginx, /grafana-lockdown\.css/);
  assert.match(css, /profile\/password/);
  assert.match(css, /display:\s*none\s*!important/);
});
