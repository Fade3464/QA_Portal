import {
  ClockCircleOutlined,
  CloseOutlined,
  DeleteOutlined,
  MessageOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons';
import { App as AntApp, Button, Input, InputNumber, Tag } from 'antd';
import { useState } from 'react';
import type { QACriterionEvidence, QAEvidencePatch } from '../types';

const { TextArea } = Input;
const EMPTY_EVIDENCE: QACriterionEvidence = { comment: '', patches: [] };

function newPatchId() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function formatEvidenceTime(milliseconds: number) {
  const seconds = Math.max(0, milliseconds) / 1000;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = (seconds % 60).toFixed(1).padStart(4, '0');
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, '0')}:${remainder}`
    : `${minutes}:${remainder}`;
}

function patchesOverlap(patches: QAEvidencePatch[]) {
  const ordered = [...patches].sort((left, right) => left.start_ms - right.start_ms);
  return ordered.some((patch, index) => index > 0 && patch.start_ms < ordered[index - 1].end_ms);
}

export function evidenceValidationError(
  evidence: Record<string, QACriterionEvidence>,
  durationSeconds: number,
) {
  for (const [criterionKey, entry] of Object.entries(evidence)) {
    if ((entry.comment ?? '').length > 2000) return `A criterion comment exceeds 2,000 characters (${criterionKey}).`;
    if ((entry.patches ?? []).length > 20) return `A criterion has more than 20 evidence patches (${criterionKey}).`;
    for (const patch of entry.patches ?? []) {
      if (!Number.isInteger(patch.start_ms) || !Number.isInteger(patch.end_ms) || patch.start_ms < 0 || patch.end_ms <= patch.start_ms) {
        return `An evidence patch has an invalid timestamp range (${criterionKey}).`;
      }
      if (durationSeconds > 0 && patch.end_ms > Math.round(durationSeconds * 1000) + 1000) {
        return `An evidence patch extends beyond the recording (${criterionKey}).`;
      }
      if ((patch.comment ?? '').length > 500) return `An evidence patch note exceeds 500 characters (${criterionKey}).`;
    }
    if (patchesOverlap(entry.patches ?? [])) return `Evidence patches overlap (${criterionKey}).`;
  }
  return '';
}

interface CriterionEvidenceEditorProps {
  criterionLabel: string;
  value?: QACriterionEvidence;
  editable: boolean;
  currentTimeSeconds: number;
  durationSeconds: number;
  onChange: (value: QACriterionEvidence) => void;
  onPlayRange: (patch: QAEvidencePatch) => void;
}

export function CriterionEvidenceEditor({
  criterionLabel,
  value = EMPTY_EVIDENCE,
  editable,
  currentTimeSeconds,
  durationSeconds,
  onChange,
  onPlayRange,
}: CriterionEvidenceEditorProps) {
  const { message } = AntApp.useApp();
  const [open, setOpen] = useState(false);
  const [pendingStart, setPendingStart] = useState<number | null>(null);
  const patches = value.patches ?? [];
  const evidenceCount = patches.length + (value.comment?.trim() ? 1 : 0);

  const updatePatch = (id: string, changes: Partial<QAEvidencePatch>) => {
    onChange({ ...value, patches: patches.map((patch) => patch.id === id ? { ...patch, ...changes } : patch) });
  };

  const captureTimestamp = () => {
    const currentMs = Math.max(0, Math.round(currentTimeSeconds * 1000));
    if (pendingStart === null) {
      setPendingStart(currentMs);
      return;
    }
    if (currentMs <= pendingStart) {
      void message.warning('Move playback beyond the start timestamp before marking the end.');
      return;
    }
    const nextPatch: QAEvidencePatch = {
      id: newPatchId(),
      start_ms: pendingStart,
      end_ms: currentMs,
      comment: '',
    };
    const nextPatches = [...patches, nextPatch].sort((left, right) => left.start_ms - right.start_ms);
    if (patchesOverlap(nextPatches)) {
      void message.warning('This range overlaps an existing patch for the same criterion.');
      return;
    }
    onChange({ ...value, patches: nextPatches });
    setPendingStart(null);
  };

  const maximumSeconds = durationSeconds > 0 ? durationSeconds : 86_400;
  return (
    <div className={`criterion-evidence${open ? ' is-open' : ''}`}>
      <Button
        className="criterion-evidence__toggle"
        type="text"
        size="small"
        icon={<MessageOutlined />}
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
      >
        {evidenceCount ? `${evidenceCount} evidence item${evidenceCount === 1 ? '' : 's'}` : 'Comment & timestamp evidence'}
      </Button>
      {open && (
        <div className="criterion-evidence__body">
          <TextArea
            value={value.comment ?? ''}
            onChange={(event) => onChange({ ...value, comment: event.target.value })}
            placeholder={`Comment on “${criterionLabel}”`}
            autoSize={{ minRows: 2, maxRows: 5 }}
            maxLength={2000}
            showCount
            disabled={!editable}
          />

          <div className="criterion-evidence__capture">
            <span><ClockCircleOutlined /> Playback at {formatEvidenceTime(Math.round(currentTimeSeconds * 1000))}</span>
            {pendingStart !== null && <Tag className="criterion-evidence__start-tag" color="processing">Start {formatEvidenceTime(pendingStart)}</Tag>}
            {editable && <Button size="small" type={pendingStart === null ? 'default' : 'primary'} onClick={captureTimestamp}>{pendingStart === null ? 'Mark start' : 'Mark end'}</Button>}
            {editable && pendingStart !== null && <Button size="small" type="text" icon={<CloseOutlined />} onClick={() => setPendingStart(null)}>Cancel</Button>}
          </div>

          {patches.length > 0 && <div className="criterion-evidence__patches">
            {patches.map((patch, index) => {
              const overlapping = patchesOverlap(patches);
              const invalid = overlapping || patch.end_ms <= patch.start_ms || patch.start_ms < 0 || patch.end_ms > maximumSeconds * 1000 + 1000;
              return <div className={`evidence-patch${invalid ? ' is-invalid' : ''}`} key={patch.id}>
                <div className="evidence-patch__range">
                  <Button type="text" size="small" icon={<PlayCircleOutlined />} onClick={() => onPlayRange(patch)}>Play</Button>
                  <span>Patch {index + 1}</span>
                  <InputNumber
                    className="evidence-patch__time"
                    size="small"
                    value={patch.start_ms / 1000}
                    min={0}
                    max={maximumSeconds}
                    step={0.1}
                    precision={1}
                    suffix="s"
                    disabled={!editable}
                    aria-label={`Patch ${index + 1} start in seconds`}
                    onChange={(next) => { if (typeof next === 'number') updatePatch(patch.id, { start_ms: Math.round(next * 1000) }); }}
                  />
                  <span>to</span>
                  <InputNumber
                    className="evidence-patch__time"
                    size="small"
                    value={patch.end_ms / 1000}
                    min={0}
                    max={maximumSeconds}
                    step={0.1}
                    precision={1}
                    suffix="s"
                    disabled={!editable}
                    aria-label={`Patch ${index + 1} end in seconds`}
                    onChange={(next) => { if (typeof next === 'number') updatePatch(patch.id, { end_ms: Math.round(next * 1000) }); }}
                  />
                  {editable && <Button danger type="text" size="small" icon={<DeleteOutlined />} aria-label={`Delete patch ${index + 1}`} onClick={() => onChange({ ...value, patches: patches.filter((item) => item.id !== patch.id) })} />}
                </div>
                <Input
                  size="small"
                  value={patch.comment ?? ''}
                  maxLength={500}
                  allowClear
                  disabled={!editable}
                  placeholder="Optional note for this audio patch"
                  onChange={(event) => updatePatch(patch.id, { comment: event.target.value })}
                />
                {invalid && <small className="evidence-patch__error">{overlapping ? 'Patches for this criterion cannot overlap.' : 'The end timestamp must be after the start and within the recording.'}</small>}
              </div>;
            })}
          </div>}
        </div>
      )}
    </div>
  );
}
