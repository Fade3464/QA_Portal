import type { QAReview } from '../types';

type EvaluationResult = Pick<QAReview, 'evaluation_type' | 'critical_errors' | 'score'>;

export function scoreDisplay(report: EvaluationResult) {
  if (report.critical_errors.length) return 'FAIL';
  if (report.evaluation_type === 'zero_defect') return 'Good';
  return report.score === null ? 'N/A' : `${report.score}%`;
}

export function outcomeColor(report: EvaluationResult) {
  if (report.critical_errors.length) return 'error';
  if (report.evaluation_type === 'zero_defect') return 'success';
  if (report.score === null) return 'default';
  const score = Number(report.score);
  if (score >= 90) return 'success';
  if (score >= 85) return 'processing';
  return 'warning';
}
