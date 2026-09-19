import {
  CheckCircleFilled,
  FileSearchOutlined,
  FormOutlined,
  LockOutlined,
  SaveOutlined,
  SendOutlined,
  UnlockOutlined,
  UsergroupAddOutlined,
  WarningFilled,
} from '@ant-design/icons';
import {
  Alert,
  App as AntApp,
  Button,
  Checkbox,
  Collapse,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Progress,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAuth } from '../auth/AuthContext';
import { api, ApiError } from '../lib/api';
import type {
  CallEvent,
  CallReservation,
  QAAnalysisResponse,
  QACategoryApplicability,
  QAEvaluationType,
  QAReview,
  QAScorecard,
} from '../types';
import type { QACriterionEvidence, QAEvidencePatch } from '../types';
import { AudioPlayer, type AudioPlaybackState, type AudioRangeRequest } from './AudioPlayerModal';
import { CriterionEvidenceEditor, evidenceValidationError } from './CriterionEvidenceEditor';
import { ContentLoader } from './LoadingStates';

const { Text, Title } = Typography;
const { TextArea } = Input;

interface Viewer { id: string; name: string }
interface EvaluationValues {
  scores: Record<string, number>;
  evaluation_type: QAEvaluationType;
  evaluation_reason: string;
  category_applicability: Record<string, QACategoryApplicability>;
  category_applicability_reasons: Record<string, string>;
  criterion_evidence: Record<string, QACriterionEvidence>;
  critical_errors: string[];
  critical_error_evidence: Record<string, QACriterionEvidence>;
  feedback_summary: string;
  strengths: string;
  expected_behavior: string;
  coaching_plan: string;
}
interface AnalysisWorkspaceModalProps {
  call: CallEvent;
  onClose: () => void;
  onReservationChange: (callId: string, reservation: CallReservation | null) => void;
}

function presenceMessage(viewers: Viewer[]) {
  const names = viewers.map((viewer) => viewer.name);
  if (names.length === 1) return `${names[0]} is also viewing this call.`;
  if (names.length === 2) return `${names[0]} and ${names[1]} are also viewing this call.`;
  return `${names[0]}, ${names[1]}, and ${names.length - 2} others are also viewing this call.`;
}

function reviewValues(review: QAReview | null): Partial<EvaluationValues> {
  return {
    scores: review?.scores ?? {},
    evaluation_type: review?.evaluation_type ?? 'full',
    evaluation_reason: review?.evaluation_reason ?? '',
    category_applicability: review?.category_applicability ?? {},
    category_applicability_reasons: review?.category_applicability_reasons ?? {},
    criterion_evidence: review?.criterion_evidence ?? {},
    critical_errors: review?.critical_errors ?? [],
    critical_error_evidence: review?.critical_error_evidence ?? {},
    feedback_summary: review?.feedback_summary ?? '',
    strengths: review?.strengths ?? '',
    expected_behavior: review?.expected_behavior ?? '',
    coaching_plan: review?.coaching_plan ?? '',
  };
}

export function AnalysisWorkspaceModal({ call, onClose, onReservationChange }: AnalysisWorkspaceModalProps) {
  const { message } = AntApp.useApp();
  const { user } = useAuth();
  const [form] = Form.useForm<EvaluationValues>();
  const watchedScoresValue = Form.useWatch('scores', form);
  const watchedEvaluationTypeValue = Form.useWatch('evaluation_type', form);
  const watchedApplicabilityValue = Form.useWatch('category_applicability', { form, preserve: true });
  const watchedCriticalValue = Form.useWatch('critical_errors', form);
  const watchedEvidenceValue = Form.useWatch('criterion_evidence', { form, preserve: true });
  const watchedCriticalEvidenceValue = Form.useWatch('critical_error_evidence', { form, preserve: true });
  const watchedScores = useMemo(() => watchedScoresValue ?? {}, [watchedScoresValue]);
  const watchedEvaluationType = watchedEvaluationTypeValue ?? 'full';
  const watchedApplicability = useMemo(() => watchedApplicabilityValue ?? {}, [watchedApplicabilityValue]);
  const watchedCritical = useMemo(() => watchedCriticalValue ?? [], [watchedCriticalValue]);
  const watchedEvidence = useMemo(() => watchedEvidenceValue ?? {}, [watchedEvidenceValue]);
  const watchedCriticalEvidence = useMemo(() => watchedCriticalEvidenceValue ?? {}, [watchedCriticalEvidenceValue]);
  const [activeCall, setActiveCall] = useState<CallEvent | null>(call);
  const [review, setReview] = useState<QAReview | null>(null);
  const [scorecard, setScorecard] = useState<QAScorecard | null>(null);
  const [viewers, setViewers] = useState<Viewer[]>([]);
  const [loading, setLoading] = useState(true);
  const [reserving, setReserving] = useState(false);
  const [releasing, setReleasing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [playback, setPlayback] = useState<AudioPlaybackState>({ currentTime: 0, duration: 0 });
  const [rangeRequest, setRangeRequest] = useState<AudioRangeRequest | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api<QAAnalysisResponse>(`/api/v1/calls/${call.id}/analysis/`, { signal: controller.signal })
      .then((result) => {
        setActiveCall(result.call);
        setReview(result.review);
        setScorecard(result.scorecard);
        form.setFieldsValue(reviewValues(result.review));
        onReservationChange(result.call.id, result.call.reservation);
      })
      .catch((requestError: unknown) => {
        if (requestError instanceof DOMException && requestError.name === 'AbortError') return;
        setActiveCall(null);
        setError(requestError instanceof Error ? requestError.message : 'The analysis workspace could not be opened.');
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [call.id, form, onReservationChange]);

  useEffect(() => {
    if (!user) return;
    let socket: WebSocket | null = null;
    let heartbeat = 0;
    let retry = 0;
    let stopped = false;
    const connect = () => {
      if (stopped) return;
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      socket = new WebSocket(`${protocol}//${window.location.host}/ws/calls/${call.id}/analysis/`);
      socket.onopen = () => {
        heartbeat = window.setInterval(() => socket?.send(JSON.stringify({ type: 'presence.heartbeat' })), 20_000);
      };
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as { type?: string; viewers?: Viewer[]; reservation?: CallReservation | null };
          if (payload.type === 'presence.updated' && payload.viewers) {
            setViewers(payload.viewers.filter((viewer) => viewer.id !== user.id));
          } else if (payload.type === 'call.reservation') {
            const reservation = payload.reservation
              ? { ...payload.reservation, is_mine: payload.reservation.reviewer_id === user.id }
              : null;
            setActiveCall((current) => current ? { ...current, reservation } : current);
            onReservationChange(call.id, reservation);
          }
        } catch {
          // Ignore malformed presence frames without interrupting the workspace.
        }
      };
      socket.onclose = () => {
        window.clearInterval(heartbeat);
        if (!stopped) retry = window.setTimeout(connect, 3000);
      };
      socket.onerror = () => socket?.close();
    };
    connect();
    return () => {
      stopped = true;
      window.clearInterval(heartbeat);
      window.clearTimeout(retry);
      socket?.close();
    };
  }, [call.id, onReservationChange, user]);

  const reservation = activeCall?.reservation ?? null;
  const mine = Boolean(reservation?.is_mine);
  const completed = review?.status === 'completed';
  const revisionRequired = review?.status === 'revision_required';
  const editable = mine && !completed;
  const lockedByAnother = Boolean(reservation && !mine);
  const visibleViewers = useMemo(() => viewers.filter((viewer) => viewer.id !== user?.id), [user?.id, viewers]);
  const categoryState = useCallback((categoryKey: string): QACategoryApplicability => {
    if (watchedEvaluationType === 'not_evaluable') return 'not_reached';
    if (watchedEvaluationType === 'full') return 'applicable';
    return watchedApplicability[categoryKey] ?? 'applicable';
  }, [watchedApplicability, watchedEvaluationType]);
  const scoreMetrics = useMemo(() => {
    if (!scorecard || watchedEvaluationType === 'not_evaluable') {
      return { earned: 0, applicable: 0, coverage: 0, score: null as number | null, tier: 'insufficient' };
    }
    let earned = 0;
    let applicable = 0;
    scorecard.categories.forEach((category) => {
      const state = categoryState(category.key);
      if (state === 'not_reached') return;
      applicable += category.max_score;
      if (state === 'applicable') {
        earned += category.criteria.reduce((total, criterion) => total + (Number(watchedScores[criterion.key]) || 0), 0);
      }
    });
    const coverage = applicable;
    const score = coverage >= (scorecard.minimum_scored_coverage ?? 20) && applicable > 0
      ? Math.round((earned / applicable) * 10_000) / 100
      : null;
    const tier = coverage < 20 ? 'insufficient' : coverage < 60 ? 'limited' : coverage < 85 ? 'partial' : 'full';
    return { earned, applicable, coverage, score, tier };
  }, [categoryState, scorecard, watchedEvaluationType, watchedScores]);
  const criticalFail = watchedCritical.length > 0;

  const changeEvaluationType = useCallback((value: QAEvaluationType) => {
    form.setFieldValue('evaluation_type', value);
    form.setFieldValue('evaluation_reason', '');
    if (!scorecard) return;
    const nextState: QACategoryApplicability = value === 'not_evaluable' ? 'not_reached' : 'applicable';
    form.setFieldValue(
      'category_applicability',
      Object.fromEntries(scorecard.categories.map((category) => [category.key, nextState])),
    );
    form.setFieldValue('category_applicability_reasons', {});
  }, [form, scorecard]);

  const changeCategoryState = useCallback((categoryKey: string, value: QACategoryApplicability) => {
    form.setFieldValue(['category_applicability', categoryKey], value);
    if (value === 'applicable') {
      form.setFieldValue(['category_applicability_reasons', categoryKey], undefined);
    }
    const category = scorecard?.categories.find((item) => item.key === categoryKey);
    if (category && value !== 'applicable') {
      const scores = { ...form.getFieldValue('scores') };
      category.criteria.forEach((criterion) => { delete scores[criterion.key]; });
      form.setFieldValue('scores', scores);
    }
  }, [form, scorecard]);

  useEffect(() => {
    if (!criticalFail || !scorecard) return;
    form.setFields(scorecard.categories.flatMap((category) => category.criteria.map((criterion) => ({
      name: ['scores', criterion.key],
      errors: [],
    }))));
  }, [criticalFail, form, scorecard]);

  const updateCriterionEvidence = useCallback((criterionKey: string, value: QACriterionEvidence) => {
    form.setFieldValue(['criterion_evidence', criterionKey], value);
  }, [form]);

  const updateCriticalEvidence = useCallback((criticalKey: string, value: QACriterionEvidence) => {
    form.setFieldValue(['critical_error_evidence', criticalKey], value);
  }, [form]);

  const evaluationValues = useCallback(() => {
    const values = form.getFieldsValue(true);
    const selectedCritical = new Set(values.critical_errors ?? []);
    return {
      ...values,
      critical_error_evidence: Object.fromEntries(
        Object.entries(values.critical_error_evidence ?? {}).filter(([key]) => selectedCritical.has(key)),
      ),
    };
  }, [form]);

  const playEvidencePatch = useCallback((patch: QAEvidencePatch) => {
    setRangeRequest({
      startSeconds: patch.start_ms / 1000,
      endSeconds: patch.end_ms / 1000,
      requestId: Date.now(),
    });
  }, []);

  const reserve = useCallback(async () => {
    if (!activeCall) return;
    setReserving(true);
    setError('');
    try {
      const next = await api<CallReservation>(`/api/v1/calls/${activeCall.id}/reserve/`, { method: 'POST' });
      const owned = { ...next, is_mine: true };
      setActiveCall((current) => current ? { ...current, reservation: owned } : current);
      onReservationChange(activeCall.id, owned);
      message.success('Call reserved. The scorecard is now editable.');
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : 'The call could not be reserved.');
    } finally {
      setReserving(false);
    }
  }, [activeCall, message, onReservationChange]);

  const release = useCallback(async () => {
    if (!activeCall) return;
    setReleasing(true);
    setError('');
    try {
      await api(`/api/v1/calls/${activeCall.id}/release/`, { method: 'POST' });
      setActiveCall((current) => current ? { ...current, reservation: null } : current);
      setReview(null);
      form.resetFields();
      onReservationChange(activeCall.id, null);
      message.success('Reservation released.');
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'The reservation could not be released.');
    } finally {
      setReleasing(false);
    }
  }, [activeCall, form, message, onReservationChange]);

  const saveDraft = useCallback(async () => {
    if (!activeCall || !editable) return;
    const values = evaluationValues();
    const duration = playback.duration || activeCall.talk_time;
    const evidenceError = evidenceValidationError(values.criterion_evidence ?? {}, duration)
      || evidenceValidationError(values.critical_error_evidence ?? {}, duration);
    if (evidenceError) {
      void message.warning(evidenceError);
      return;
    }
    setSaving(true);
    setError('');
    try {
      const saved = await api<QAReview>(`/api/v1/calls/${activeCall.id}/review/`, {
        method: 'PATCH', body: JSON.stringify(values),
      });
      setReview(saved);
      message.success('Draft saved.');
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'The draft could not be saved.');
    } finally {
      setSaving(false);
    }
  }, [activeCall, editable, evaluationValues, message, playback.duration]);

  const submit = useCallback(async () => {
    if (!activeCall || !editable || !scorecard) return;
    setSubmitting(true);
    setError('');
    try {
      await form.validateFields();
      const values = evaluationValues();
      const isAutomaticFail = (values.critical_errors ?? []).length > 0;
      if (!isAutomaticFail) {
        const missingCriteria = scorecard.categories
          .filter((category) => {
            const state = values.evaluation_type === 'not_evaluable'
              ? 'not_reached'
              : values.evaluation_type === 'full'
                ? 'applicable'
                : values.category_applicability?.[category.key] ?? 'applicable';
            return state === 'applicable';
          })
          .flatMap((category) => category.criteria).filter((criterion) => {
          const value = values.scores?.[criterion.key];
          return value === undefined || value === null;
        });
        if (missingCriteria.length > 0) {
          form.setFields(missingCriteria.map((criterion) => ({
            name: ['scores', criterion.key],
            errors: ['Required unless a critical error is selected'],
          })));
          void message.warning('Complete all scorecard fields or select a critical error.');
          return;
        }
      }
      if (values.evaluation_type === 'agent_premature'
        && !Object.values(values.category_applicability ?? {}).includes('missed_opportunity')) {
        void message.warning('Mark the heading the agent had an opportunity to complete.');
        return;
      }
      const duration = playback.duration || activeCall.talk_time;
      const evidenceError = evidenceValidationError(values.criterion_evidence ?? {}, duration)
        || evidenceValidationError(values.critical_error_evidence ?? {}, duration);
      if (evidenceError) {
        void message.warning(evidenceError);
        return;
      }
      const submitted = await api<QAReview>(`/api/v1/calls/${activeCall.id}/review/submit/`, {
        method: 'POST', body: JSON.stringify(values),
      });
      setReview(submitted);
      const nextReservation: CallReservation = {
        review_id: submitted.id, reviewer_id: submitted.reviewer, reviewer_name: submitted.reviewer_name,
        status: submitted.status, reserved_at: submitted.assigned_at, is_mine: true,
      };
      setActiveCall((current) => current ? { ...current, reservation: nextReservation } : current);
      onReservationChange(activeCall.id, nextReservation);
      message.success(revisionRequired ? 'Reassessed report resubmitted to the Team Leader.' : 'Report submitted to the Team Leader.');
    } catch (requestError) {
      if (requestError && typeof requestError === 'object' && 'errorFields' in requestError) {
        message.warning('Complete all required scorecard fields.');
      } else {
        setError(requestError instanceof Error ? requestError.message : 'The report could not be submitted.');
      }
    } finally {
      setSubmitting(false);
    }
  }, [activeCall, editable, evaluationValues, form, message, onReservationChange, playback.duration, revisionRequired, scorecard]);

  const categoryItems = scorecard?.categories.map((category) => {
    const state = categoryState(category.key);
    const categoryScore = state === 'applicable'
      ? category.criteria.reduce((total, criterion) => total + (Number(watchedScores[criterion.key]) || 0), 0)
      : 0;
    const statusLabel = state === 'not_reached'
      ? 'Not reached'
      : state === 'missed_opportunity'
        ? 'Missed · 0'
        : `${categoryScore}/${category.max_score}`;
    return {
      key: category.key,
      label: <span className="qa-category-label"><strong>{category.label}</strong><span>{statusLabel}</span></span>,
      extra: watchedEvaluationType !== 'full' && watchedEvaluationType !== 'not_evaluable' ? (
        <div className="qa-category-state" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
          <Select
            size="small"
            value={state}
            options={scorecard.applicability_states}
            onChange={(value) => changeCategoryState(category.key, value as QACategoryApplicability)}
          />
        </div>
      ) : undefined,
      children: state === 'not_reached' ? (
        <div className="qa-heading-exclusion">
          <Text type="secondary">Excluded from the quality score and coverage denominator.</Text>
          <Form.Item
            name={['category_applicability_reasons', category.key]}
            label="Why was this heading not reached?"
            rules={[{ required: true, message: 'Select a reason' }]}
          >
            <Select options={scorecard.applicability_reasons} placeholder="Select reason" />
          </Form.Item>
        </div>
      ) : <div className="qa-criteria-list">
        {state === 'missed_opportunity' && <div className="qa-heading-exclusion qa-heading-exclusion--missed">
          <Text>The agent had the opportunity to complete this stage, so the heading scores zero.</Text>
          <Form.Item
            name={['category_applicability_reasons', category.key]}
            label="Why was this a missed opportunity?"
            rules={[{ required: true, message: 'Select a reason' }]}
          >
            <Select options={scorecard.applicability_reasons} placeholder="Select reason" />
          </Form.Item>
        </div>}
        {category.criteria.map((criterion) => (
        <div className="qa-criterion" key={criterion.key}>
          <span><strong>{criterion.label}</strong><small>Maximum {criterion.max_score} points</small></span>
          <Form.Item name={['scores', criterion.key]} noStyle>
            <InputNumber
              min={0}
              max={criterion.max_score}
              precision={1}
              step={0.5}
              controls
              disabled={!editable || state === 'missed_opportunity'}
              placeholder={state === 'missed_opportunity' ? '0' : undefined}
              aria-label={`${criterion.label} score. Press Alt to enter the maximum score.`}
              aria-keyshortcuts="Alt"
              onKeyDown={(event) => {
                if (event.key !== 'Alt' || event.repeat || !editable || state !== 'applicable') return;
                event.preventDefault();
                form.setFieldValue(['scores', criterion.key], criterion.max_score);
                form.setFields([{ name: ['scores', criterion.key], errors: [] }]);
              }}
            />
          </Form.Item>
          <CriterionEvidenceEditor
            criterionLabel={criterion.label}
            value={watchedEvidence[criterion.key]}
            editable={editable}
            currentTimeSeconds={playback.currentTime}
            durationSeconds={playback.duration || activeCall?.talk_time || 0}
            onChange={(value) => updateCriterionEvidence(criterion.key, value)}
            onPlayRange={playEvidencePatch}
          />
        </div>
      ))}</div>,
    };
  }) ?? [];

  return <Modal open onCancel={onClose} footer={null} width="min(1540px, calc(100vw - 40px))" destroyOnHidden mask={{ closable: false, blur: true }} classNames={{ container: 'analysis-modal__container', header: 'analysis-modal__header', body: 'analysis-modal__body' }} title={(
    <div className="analysis-modal__title"><span className="analysis-modal__title-icon"><FileSearchOutlined /></span><span><Title level={4}>Call analysis</Title><Text type="secondary">{activeCall?.phone_number || 'Unknown number'} · {activeCall?.agent_name || activeCall?.agent_user || 'Unknown agent'}</Text></span><span className="analysis-modal__status">{completed ? <Tag icon={<CheckCircleFilled />} color="success">Report submitted</Tag> : mine ? <Tag icon={<CheckCircleFilled />} color="processing">Reserved by you</Tag> : lockedByAnother ? <Tag icon={<LockOutlined />} color="warning">Reserved by {reservation?.reviewer_name}</Tag> : <Tag>Available</Tag>}</span></div>
  )}>
    {loading ? <ContentLoader label="Preparing analysis workspace" minHeight={620} /> : error && !activeCall ? <Alert type="error" showIcon title="Unable to open analysis" description={error} /> : activeCall && <div className="analysis-workspace data-reveal">
      {visibleViewers.length > 0 && <Alert className="analysis-presence" type="info" showIcon icon={<UsergroupAddOutlined />} title={presenceMessage(visibleViewers)} />}
      {revisionRequired && <Alert className="analysis-revision-request" type="warning" showIcon title={`Reassessment requested${review.revision_count > 1 ? ` · revision ${review.revision_count}` : ''}`} description={<span><strong>Team Leader feedback:</strong> {review.revision_reason}</span>} />}
      {error && <Alert type="error" showIcon title="Action unsuccessful" description={error} closable={{ onClose: () => setError('') }} />}
      <div className="analysis-workspace__toolbar"><Text type="secondary">{completed ? `Submitted to ${review?.team_leader_name}.` : revisionRequired ? 'Update the evaluation against the Team Leader’s feedback, then resubmit it.' : 'Reserve the call before entering or saving QA findings.'}</Text><Space>{!reservation && <Button type="primary" icon={<LockOutlined />} loading={reserving} onClick={() => void reserve()}>Reserve</Button>}{mine && !completed && !revisionRequired && <Popconfirm title="Release this call?" description="Your draft will be deleted and another QA analyst can reserve it." okText="Release" okButtonProps={{ danger: true }} onConfirm={release}><Button danger icon={<UnlockOutlined />} loading={releasing}>Release</Button></Popconfirm>}</Space></div>
      <div className="analysis-workspace__columns">
        <section className="analysis-panel analysis-panel--audio" aria-label="Call recording tools"><div className="analysis-panel__heading"><span><FileSearchOutlined /></span><div><strong>Recording</strong><small>Listen, seek, adjust speed, or download</small></div></div><AudioPlayer call={activeCall} onPlaybackStateChange={setPlayback} rangeRequest={rangeRequest} /></section>
        <section className={`analysis-panel analysis-panel--form${editable || completed ? '' : ' is-locked'}`} aria-label="QA evaluation form">
          <div className="analysis-panel__heading"><span><FormOutlined /></span><div><strong>QA evaluation</strong><small>{completed ? `${review?.rating_label} · ${review?.outcome_label}` : revisionRequired ? 'Reassessment in progress · review the return reason above' : editable ? 'Score all criteria, then document actionable feedback' : lockedByAnother ? `Locked by ${reservation?.reviewer_name}` : 'Reserve this call to begin'}</small></div></div>
          {!editable && !completed ? <div className="analysis-form-placeholder"><span className="analysis-form-placeholder__icon"><LockOutlined /></span><strong>{lockedByAnother ? 'This call is reserved' : 'Reserve to unlock the scorecard'}</strong><Text type="secondary">{lockedByAnother ? `${reservation?.reviewer_name} currently owns this analysis.` : 'Reservation prevents duplicate assessments while you work.'}</Text></div> : scorecard && <Form form={form} layout="vertical" className="qa-scorecard" disabled={!editable}>
            <div className="qa-call-classification">
              <div><strong>How much of the call could be evaluated?</strong><Text type="secondary">Choose the call outcome first. Only applicable headings affect quality.</Text></div>
              <Form.Item name="evaluation_type" noStyle>
                <Select
                  className="qa-call-classification__select"
                  options={scorecard.evaluation_types}
                  onChange={(value) => changeEvaluationType(value as QAEvaluationType)}
                />
              </Form.Item>
            </div>
            {watchedEvaluationType === 'not_evaluable' && <div className="qa-not-evaluable">
              <Alert type="info" showIcon title="No numeric score will be created" description="This report remains visible for operational tracking but is excluded from quality averages." />
              <Form.Item name="evaluation_reason" label="Why is this call not evaluable?" rules={[{ required: true, message: 'Select a reason' }]}>
                <Select options={scorecard.applicability_reasons} placeholder="Select reason" />
              </Form.Item>
            </div>}
            <div className={`qa-score-summary${criticalFail ? ' qa-score-summary--critical' : ''}`}>
              <Progress
                type="circle"
                percent={criticalFail ? 0 : scoreMetrics.score ?? 0}
                size={92}
                status={criticalFail ? 'exception' : scoreMetrics.score !== null && scoreMetrics.score >= scorecard.benchmark ? 'success' : 'normal'}
                format={() => criticalFail ? 'FAIL' : scoreMetrics.score === null ? 'N/A' : `${scoreMetrics.score}%`}
              />
              <span>
                <strong>{criticalFail ? 'Automatic failure' : scoreMetrics.score === null ? 'Not enough interaction to score' : scoreMetrics.score >= scorecard.benchmark ? 'Meets benchmark' : 'Below benchmark'}</strong>
                <small>{criticalFail ? 'Scorecard completion is optional for this escalation.' : `Quality ${scoreMetrics.score === null ? 'not scored' : `${scoreMetrics.score}/100`} · coverage ${scoreMetrics.coverage}% (${scoreMetrics.tier})`}</small>
              </span>
            </div>
            {watchedEvaluationType !== 'not_evaluable' && <Collapse items={categoryItems} defaultActiveKey={[scorecard.categories[0]?.key]} size="small" />}
            <div className="qa-critical-block"><div><WarningFilled /><span><strong>Critical error override</strong><small>Selecting any item results in an automatic fail and immediate escalation.</small></span></div><Form.Item name="critical_errors"><Checkbox.Group options={scorecard.critical_errors.map((item) => ({ label: item.label, value: item.value }))} className="qa-critical-options" /></Form.Item>{watchedCritical.length > 0 && <div className="qa-critical-evidence"><Text type="secondary">Document each selected violation and attach the exact recording segments that support it.</Text>{watchedCritical.map((criticalKey) => { const critical = scorecard.critical_errors.find((item) => item.value === criticalKey); return <div className="qa-critical-evidence__item" key={criticalKey}><strong>{critical?.label ?? criticalKey}</strong><CriterionEvidenceEditor criterionLabel={critical?.label ?? criticalKey} value={watchedCriticalEvidence[criticalKey]} editable={editable} currentTimeSeconds={playback.currentTime} durationSeconds={playback.duration || activeCall?.talk_time || 0} onChange={(value) => updateCriticalEvidence(criticalKey, value)} onPlayRange={playEvidencePatch} /></div>; })}</div>}</div>
            <div className="qa-feedback-grid"><Form.Item name="feedback_summary" label="What happened and why it matters"><TextArea rows={3} maxLength={4000} showCount /></Form.Item><Form.Item name="strengths" label="Strengths observed"><TextArea rows={3} maxLength={4000} showCount /></Form.Item><Form.Item name="expected_behavior" label="Expected behavior"><TextArea rows={3} maxLength={4000} showCount /></Form.Item><Form.Item name="coaching_plan" label="Recommended coaching / follow-up"><TextArea rows={3} maxLength={4000} showCount /></Form.Item></div>
            {editable && <div className="qa-form-actions"><Button icon={<SaveOutlined />} loading={saving} onClick={() => void saveDraft()}>Save draft</Button><Popconfirm title={revisionRequired ? 'Resubmit this QA report?' : 'Submit this QA report?'} description={revisionRequired ? 'The revised evaluation will be locked and returned to the Team Leader’s queue.' : 'The report will be locked and sent to the agent’s Team Leader.'} okText={revisionRequired ? 'Resubmit report' : 'Submit report'} onConfirm={submit}><Button type="primary" icon={<SendOutlined />} loading={submitting}>{revisionRequired ? 'Resubmit report' : 'Submit report'}</Button></Popconfirm></div>}
          </Form>}
        </section>
      </div>
    </div>}
  </Modal>;
}
