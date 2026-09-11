import {
  CheckCircleFilled,
  FileSearchOutlined,
  FormOutlined,
  LockOutlined,
  UnlockOutlined,
  UsergroupAddOutlined,
} from '@ant-design/icons';
import { Alert, App as AntApp, Button, Modal, Popconfirm, Tag, Typography } from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAuth } from '../auth/AuthContext';
import { api, ApiError } from '../lib/api';
import type { CallEvent, CallReservation } from '../types';
import { AudioPlayer } from './AudioPlayerModal';
import { PortalLoader } from './PortalLoader';

const { Text, Title } = Typography;

interface Viewer {
  id: string;
  name: string;
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

export function AnalysisWorkspaceModal({ call, onClose, onReservationChange }: AnalysisWorkspaceModalProps) {
  const { message } = AntApp.useApp();
  const { user } = useAuth();
  const [activeCall, setActiveCall] = useState<CallEvent | null>(call);
  const [viewers, setViewers] = useState<Viewer[]>([]);
  const [loading, setLoading] = useState(true);
  const [reserving, setReserving] = useState(false);
  const [releasing, setReleasing] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    api<CallEvent>(`/api/v1/calls/${call.id}/analysis/`, { signal: controller.signal })
      .then((freshCall) => {
        setActiveCall(freshCall);
        onReservationChange(freshCall.id, freshCall.reservation);
      })
      .catch((requestError: unknown) => {
        if (requestError instanceof DOMException && requestError.name === 'AbortError') return;
        setError(requestError instanceof Error ? requestError.message : 'The analysis workspace could not be opened.');
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [call, onReservationChange]);

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
          const payload = JSON.parse(event.data) as {
            type?: string;
            viewers?: Viewer[];
            reservation?: CallReservation | null;
          };
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
  }, [call, onReservationChange, user]);

  const reservation = activeCall?.reservation ?? null;
  const mine = Boolean(reservation?.is_mine);
  const lockedByAnother = Boolean(reservation && !mine);
  const visibleViewers = useMemo(() => viewers.filter((viewer) => viewer.id !== user?.id), [user?.id, viewers]);

  const reserve = useCallback(async () => {
    if (!activeCall) return;
    setReserving(true);
    setError('');
    try {
      const next = await api<CallReservation>(`/api/v1/calls/${activeCall.id}/reserve/`, { method: 'POST' });
      const owned = { ...next, is_mine: true };
      setActiveCall((current) => current ? { ...current, reservation: owned } : current);
      onReservationChange(activeCall.id, owned);
      message.success('Call reserved for your analysis.');
    } catch (requestError) {
      const detail = requestError instanceof ApiError ? requestError.message : 'The call could not be reserved.';
      setError(detail);
      if (requestError instanceof ApiError && requestError.status === 409) {
        const fresh = await api<CallEvent>(`/api/v1/calls/${activeCall.id}/analysis/`).catch(() => null);
        if (fresh) {
          setActiveCall(fresh);
          onReservationChange(fresh.id, fresh.reservation);
        }
      }
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
      onReservationChange(activeCall.id, null);
      message.success('Reservation released.');
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'The reservation could not be released.');
    } finally {
      setReleasing(false);
    }
  }, [activeCall, message, onReservationChange]);

  return (
    <Modal
      open
      onCancel={onClose}
      footer={null}
      width="min(1480px, calc(100vw - 40px))"
      destroyOnHidden
      mask={{ closable: false, blur: true }}
      classNames={{ container: 'analysis-modal__container', header: 'analysis-modal__header', body: 'analysis-modal__body' }}
      title={(
        <div className="analysis-modal__title">
          <span className="analysis-modal__title-icon"><FileSearchOutlined /></span>
          <span><Title level={4}>Call analysis</Title><Text type="secondary">{activeCall?.phone_number || 'Unknown number'} · {activeCall?.agent_name || activeCall?.agent_user || 'Unknown agent'}</Text></span>
          <span className="analysis-modal__status">
            {mine ? <Tag icon={<CheckCircleFilled />} color="success">Reserved by you</Tag> : lockedByAnother ? <Tag icon={<LockOutlined />} color="warning">Reserved by {reservation?.reviewer_name}</Tag> : <Tag>Available</Tag>}
          </span>
        </div>
      )}
    >
      {loading ? <div className="analysis-modal__loading"><PortalLoader label="Preparing analysis workspace…" /></div> : error && !activeCall ? <Alert type="error" showIcon title="Unable to open analysis" description={error} /> : activeCall && (
        <div className="analysis-workspace">
          {visibleViewers.length > 0 && <Alert className="analysis-presence" type="info" showIcon icon={<UsergroupAddOutlined />} title={presenceMessage(visibleViewers)} />}
          {error && <Alert type="error" showIcon title="Action unsuccessful" description={error} closable={{ onClose: () => setError('') }} />}
          <div className="analysis-workspace__toolbar">
            <Text type="secondary">Reserve the call before entering or saving QA findings.</Text>
            <span>
              {!reservation && <Button type="primary" icon={<LockOutlined />} loading={reserving} onClick={() => void reserve()}>Reserve</Button>}
              {mine && (
                <Popconfirm title="Release this call?" description="Another QA analyst will be able to reserve it." okText="Release" okButtonProps={{ danger: true }} onConfirm={release}>
                  <Button danger icon={<UnlockOutlined />} loading={releasing}>Release</Button>
                </Popconfirm>
              )}
            </span>
          </div>
          <div className="analysis-workspace__columns">
            <section className="analysis-panel analysis-panel--audio" aria-label="Call recording tools">
              <div className="analysis-panel__heading"><span><FileSearchOutlined /></span><div><strong>Recording</strong><small>Listen, seek, adjust speed, or download</small></div></div>
              <AudioPlayer call={activeCall} />
            </section>
            <section className={`analysis-panel analysis-panel--form${mine ? '' : ' is-locked'}`} aria-label="QA evaluation form">
              <div className="analysis-panel__heading"><span><FormOutlined /></span><div><strong>QA evaluation</strong><small>{mine ? 'Reserved and ready for assessment' : lockedByAnother ? `Locked by ${reservation?.reviewer_name}` : 'Reserve this call to begin'}</small></div></div>
              <div className="analysis-form-placeholder">
                <span className="analysis-form-placeholder__icon">{mine ? <FormOutlined /> : <LockOutlined />}</span>
                <strong>{mine ? 'Evaluation form coming next' : lockedByAnother ? 'This call is reserved' : 'Reserve to unlock the QA form'}</strong>
                <Text type="secondary">{mine ? 'The scoring fields and criteria will be configured in the next step.' : lockedByAnother ? `${reservation?.reviewer_name} currently owns this analysis.` : 'Reservation prevents duplicate assessments while you work.'}</Text>
              </div>
            </section>
          </div>
        </div>
      )}
    </Modal>
  );
}
