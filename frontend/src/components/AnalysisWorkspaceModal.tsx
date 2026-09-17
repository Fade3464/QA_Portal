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
  Space,
  Tag,
  Typography,
} from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAuth } from '../auth/AuthContext';
import { api, ApiError } from '../lib/api';
import type { CallEvent, CallReservation, QAAnalysisResponse, QAReview, QAScorecard } from '../types';
import type { QACriterionEvidence, QAEvidencePatch } from '../types';
import { AudioPlayer, type AudioPlaybackState, type AudioRangeRequest } from './AudioPlayerModal';
import { CriterionEvidenceEditor, evidenceValidationError } from './CriterionEvidenceEditor';
import { PortalLoader } from './PortalLoader';

const { Text, Title } = Typography;
const { TextArea } = Input;

interface Viewer { id: string; name: string }
interface EvaluationValues {
  scores: Record<string, number>;
  criterion_evidence: Record<string, QACriterionEvidence>;
  critical_errors: string[];
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
    criterion_evidence: review?.criterion_evidence ?? {},
    critical_errors: review?.critical_errors ?? [],
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
  const watchedCriticalValue = Form.useWatch('critical_errors', form);
  const watchedEvidenceValue = Form.useWatch('criterion_evidence', { form, preserve: true });
  const watchedScores = useMemo(() => watchedScoresValue ?? {}, [watchedScoresValue]);
  const watchedCritical = useMemo(() => watchedCriticalValue ?? [], [watchedCriticalValue]);
  const watchedEvidence = useMemo(() => watchedEvidenceValue ?? {}, [watchedEvidenceValue]);
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
  const editable = mine && !completed;
  const lockedByAnother = Boolean(reservation && !mine);
  const visibleViewers = useMemo(() => viewers.filter((viewer) => viewer.id !== user?.id), [user?.id, viewers]);
  const score = useMemo(() => Object.values(watchedScores).reduce((total, value) => total + (Number(value) || 0), 0), [watchedScores]);
  const criticalFail = watchedCritical.length > 0;

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
    const values = form.getFieldsValue(true);
    const evidenceError = evidenceValidationError(values.criterion_evidence ?? {}, playback.duration || activeCall.talk_time);
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
  }, [activeCall, editable, form, message, playback.duration]);

  const submit = useCallback(async () => {
    if (!activeCall || !editable || !scorecard) return;
    setSubmitting(true);
    setError('');
    try {
      const values = await form.validateFields();
      const isAutomaticFail = (values.critical_errors ?? []).length > 0;
      if (!isAutomaticFail) {
        const missingCriteria = scorecard.categories.flatMap((category) => category.criteria).filter((criterion) => {
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
      const evidenceError = evidenceValidationError(values.criterion_evidence ?? {}, playback.duration || activeCall.talk_time);
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
      message.success('Report submitted to the Team Leader.');
    } catch (requestError) {
      if (requestError && typeof requestError === 'object' && 'errorFields' in requestError) {
        message.warning('Complete all required scorecard fields.');
      } else {
        setError(requestError instanceof Error ? requestError.message : 'The report could not be submitted.');
      }
    } finally {
      setSubmitting(false);
    }
  }, [activeCall, editable, form, message, onReservationChange, playback.duration, scorecard]);

  const categoryItems = scorecard?.categories.map((category) => {
    const categoryScore = category.criteria.reduce((total, criterion) => total + (Number(watchedScores[criterion.key]) || 0), 0);
    return {
      key: category.key,
      label: <span className="qa-category-label"><strong>{category.label}</strong><span>{categoryScore}/{category.max_score}</span></span>,
      children: <div className="qa-criteria-list">{category.criteria.map((criterion) => (
        <div className="qa-criterion" key={criterion.key}>
          <span><strong>{criterion.label}</strong><small>Maximum {criterion.max_score} points</small></span>
          <Form.Item name={['scores', criterion.key]} noStyle>
            <InputNumber min={0} max={criterion.max_score} precision={1} step={0.5} controls disabled={!editable} aria-label={`${criterion.label} score`} />
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
    {loading ? <div className="analysis-modal__loading"><PortalLoader label="Preparing analysis workspace…" /></div> : error && !activeCall ? <Alert type="error" showIcon title="Unable to open analysis" description={error} /> : activeCall && <div className="analysis-workspace">
      {visibleViewers.length > 0 && <Alert className="analysis-presence" type="info" showIcon icon={<UsergroupAddOutlined />} title={presenceMessage(visibleViewers)} />}
      {error && <Alert type="error" showIcon title="Action unsuccessful" description={error} closable={{ onClose: () => setError('') }} />}
      <div className="analysis-workspace__toolbar"><Text type="secondary">{completed ? `Submitted to ${review?.team_leader_name}.` : 'Reserve the call before entering or saving QA findings.'}</Text><Space>{!reservation && <Button type="primary" icon={<LockOutlined />} loading={reserving} onClick={() => void reserve()}>Reserve</Button>}{mine && !completed && <Popconfirm title="Release this call?" description="Your draft will be deleted and another QA analyst can reserve it." okText="Release" okButtonProps={{ danger: true }} onConfirm={release}><Button danger icon={<UnlockOutlined />} loading={releasing}>Release</Button></Popconfirm>}</Space></div>
      <div className="analysis-workspace__columns">
        <section className="analysis-panel analysis-panel--audio" aria-label="Call recording tools"><div className="analysis-panel__heading"><span><FileSearchOutlined /></span><div><strong>Recording</strong><small>Listen, seek, adjust speed, or download</small></div></div><AudioPlayer call={activeCall} onPlaybackStateChange={setPlayback} rangeRequest={rangeRequest} /></section>
        <section className={`analysis-panel analysis-panel--form${editable || completed ? '' : ' is-locked'}`} aria-label="QA evaluation form">
          <div className="analysis-panel__heading"><span><FormOutlined /></span><div><strong>QA evaluation</strong><small>{completed ? `${review?.rating_label} · ${review?.outcome_label}` : editable ? 'Score all criteria, then document actionable feedback' : lockedByAnother ? `Locked by ${reservation?.reviewer_name}` : 'Reserve this call to begin'}</small></div></div>
          {!editable && !completed ? <div className="analysis-form-placeholder"><span className="analysis-form-placeholder__icon"><LockOutlined /></span><strong>{lockedByAnother ? 'This call is reserved' : 'Reserve to unlock the scorecard'}</strong><Text type="secondary">{lockedByAnother ? `${reservation?.reviewer_name} currently owns this analysis.` : 'Reservation prevents duplicate assessments while you work.'}</Text></div> : scorecard && <Form form={form} layout="vertical" className="qa-scorecard" disabled={!editable}>
            <div className={`qa-score-summary${criticalFail ? ' qa-score-summary--critical' : ''}`}><Progress type="circle" percent={score} size={92} status={criticalFail ? 'exception' : score >= scorecard.benchmark ? 'success' : 'normal'} format={() => criticalFail ? 'FAIL' : `${score}%`} /><span><strong>{criticalFail ? 'Automatic failure' : score >= scorecard.benchmark ? 'Meets benchmark' : 'Below benchmark'}</strong><small>{criticalFail ? 'Scorecard completion is optional for this escalation.' : `Numeric score ${score}/100 · benchmark ${scorecard.benchmark}%`}</small></span></div>
            <Collapse items={categoryItems} defaultActiveKey={[scorecard.categories[0]?.key]} size="small" />
            <div className="qa-critical-block"><div><WarningFilled /><span><strong>Critical error override</strong><small>Selecting any item results in an automatic fail and immediate escalation.</small></span></div><Form.Item name="critical_errors"><Checkbox.Group options={scorecard.critical_errors.map((item) => ({ label: item.label, value: item.value }))} className="qa-critical-options" /></Form.Item></div>
            <div className="qa-feedback-grid"><Form.Item name="feedback_summary" label="What happened and why it matters"><TextArea rows={3} maxLength={4000} showCount /></Form.Item><Form.Item name="strengths" label="Strengths observed"><TextArea rows={3} maxLength={4000} showCount /></Form.Item><Form.Item name="expected_behavior" label="Expected behavior"><TextArea rows={3} maxLength={4000} showCount /></Form.Item><Form.Item name="coaching_plan" label="Recommended coaching / follow-up"><TextArea rows={3} maxLength={4000} showCount /></Form.Item></div>
            {editable && <div className="qa-form-actions"><Button icon={<SaveOutlined />} loading={saving} onClick={() => void saveDraft()}>Save draft</Button><Popconfirm title="Submit this QA report?" description="The report will be locked and sent to the agent’s Team Leader." okText="Submit report" onConfirm={submit}><Button type="primary" icon={<SendOutlined />} loading={submitting}>Submit report</Button></Popconfirm></div>}
          </Form>}
        </section>
      </div>
    </div>}
  </Modal>;
}
