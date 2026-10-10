import assert from 'node:assert/strict';
import test from 'node:test';
import { theme } from 'antd';
import { createWorkspaceTheme, THEME_PRESETS } from '../src/theme/styles.ts';

const luminance = (hex) => {
  const values = hex.slice(1).match(/.{2}/g).map((part) => parseInt(part, 16) / 255)
    .map((v) => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
  return values[0] * 0.2126 + values[1] * 0.7152 + values[2] * 0.0722;
};

test('only the requested five workspace styles are exposed', () => {
  assert.deepEqual(THEME_PRESETS.map((p) => p.id), ['default', 'mui', 'shadcn', 'glass', 'geek']);
});
for (const dark of [false, true]) {
  test(`every style has a distinct ${dark ? 'dark' : 'light'} background`, () => {
    const backgrounds = THEME_PRESETS.map(({ id }) => createWorkspaceTheme(id, dark, false).theme.token.colorBgLayout);
    assert.equal(new Set(backgrounds).size, 5);
    for (const bg of backgrounds) assert.ok(dark ? luminance(bg) < 0.03 : luminance(bg) > 0.8);
  });
  for (const { id } of THEME_PRESETS) {
    test(`${id} ${dark ? 'dark' : 'light'}: compact composition, surfaces and readable filled button`, () => {
      const normal = createWorkspaceTheme(id, dark, false).theme;
      const compact = createWorkspaceTheme(id, dark, true).theme;
      assert.deepEqual(normal.algorithm, [dark ? theme.darkAlgorithm : theme.defaultAlgorithm]);
      assert.deepEqual(compact.algorithm, [...normal.algorithm, theme.compactAlgorithm]);
      assert.equal(normal.inherit, false, 'The root theme must not inherit light seeds');
      assert.equal(normal.token.colorTextBase, dark ? '#ffffff' : '#000000');
      const normalToken = theme.getDesignToken(normal);
      const compactToken = theme.getDesignToken(compact);
      assert.ok(compactToken.controlHeight < normalToken.controlHeight);
      assert.equal(compactToken.colorBgLayout, normalToken.colorBgLayout);
      assert.notEqual(normalToken.colorBgContainer, normalToken.colorBgLayout);
      const a = luminance(normal.token.colorPrimary);
      const b = luminance(normal.components.Button.primaryColor);
      assert.ok((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) >= 3, 'Filled button text needs contrast');
      assert.equal(normal.components.Table.headerBg, normalToken.colorFillAlter);
      assert.equal(normal.components.Layout.lightSiderBg, normalToken.colorBgContainer);
    });
  }
}
