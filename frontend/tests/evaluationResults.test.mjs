import assert from 'node:assert/strict';
import test from 'node:test';
import { scoreDisplay, outcomeColor } from '../src/lib/evaluationResults.ts';

test('unscored non-evaluable calls show N/A with a neutral result', () => {
  const result = { evaluation_type: 'not_evaluable', critical_errors: [], score: null };
  assert.equal(scoreDisplay(result), 'N/A');
  assert.equal(outcomeColor(result), 'default');
});

test('critical results stay failures with or without a numeric score', () => {
  for (const score of [null, '98.00']) {
    const result = { evaluation_type: 'partial', critical_errors: ['misrepresentation'], score };
    assert.equal(scoreDisplay(result), 'FAIL');
    assert.equal(outcomeColor(result), 'error');
  }
});

test('zero-defect and scored calls retain their distinct results', () => {
  assert.equal(scoreDisplay({ evaluation_type: 'zero_defect', critical_errors: [], score: null }), 'Good');
  assert.equal(outcomeColor({ evaluation_type: 'zero_defect', critical_errors: [], score: null }), 'success');
  assert.equal(scoreDisplay({ evaluation_type: 'full', critical_errors: [], score: '0.00' }), '0.00%');
  assert.equal(scoreDisplay({ evaluation_type: 'full', critical_errors: [], score: '95.00' }), '95.00%');
});
