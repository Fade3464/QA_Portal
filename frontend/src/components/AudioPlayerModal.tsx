import {
  AudioMutedOutlined,
  BackwardOutlined,
  CustomerServiceOutlined,
  DownloadOutlined,
  ForwardOutlined,
  PauseOutlined,
  PlayCircleFilled,
  SoundOutlined,
} from '@ant-design/icons';
import { Button, Modal, Select, Slider, Tag, Typography } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { CallEvent } from '../types';

const { Text, Title } = Typography;
const PLAYBACK_RATES = [0.75, 1, 1.25, 1.5, 2];
const VISUALIZER_BARS = [30, 54, 72, 42, 86, 62, 36, 76, 50, 92, 58, 34, 68, 82, 46, 64, 88, 52, 74, 40, 60, 80, 48, 70];

interface AudioPlayerModalProps {
  call: CallEvent | null;
  onClose: () => void;
}

function formatTime(value: number) {
  if (!Number.isFinite(value) || value < 0) return '0:00';
  const totalSeconds = Math.floor(value);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    : `${minutes}:${String(seconds).padStart(2, '0')}`;
}

export function AudioPlayer({ call }: { call: CallEvent }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isBuffering, setIsBuffering] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [error, setError] = useState('');
  const recordingUrl = useMemo(() => `/api/v1/calls/${call.id}/recording/`, [call]);

  useEffect(() => {
    const audio = audioRef.current;
    return () => {
      audio?.pause();
    };
  }, [call]);

  const togglePlayback = async () => {
    const audio = audioRef.current;
    if (!audio) return;
    setError('');
    if (!audio.paused) {
      audio.pause();
      return;
    }
    try {
      await audio.play();
    } catch {
      setIsBuffering(false);
      setError('This recording could not be played. Try downloading it instead.');
    }
  };

  const seek = (value: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = value;
    setCurrentTime(value);
  };

  const skip = (seconds: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    const nextTime = Math.max(0, Math.min(audio.duration || duration || 0, audio.currentTime + seconds));
    seek(nextTime);
  };

  const changeVolume = (value: number) => {
    const audio = audioRef.current;
    if (audio) {
      audio.volume = value;
      audio.muted = false;
    }
    setVolume(value);
    setMuted(false);
  };

  const toggleMute = () => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.muted = !muted;
    setMuted(!muted);
  };

  const changePlaybackRate = (value: number) => {
    const audio = audioRef.current;
    if (audio) audio.playbackRate = value;
    setPlaybackRate(value);
  };

  return (
      <div className="audio-player">
        <audio
          ref={audioRef}
          src={recordingUrl}
          preload="metadata"
          onLoadedMetadata={(event) => setDuration(event.currentTarget.duration)}
          onDurationChange={(event) => setDuration(event.currentTarget.duration)}
          onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          onWaiting={() => setIsBuffering(true)}
          onPlaying={() => setIsBuffering(false)}
          onCanPlay={() => setIsBuffering(false)}
          onEnded={() => setIsPlaying(false)}
          onError={() => {
            setIsBuffering(false);
            setError('This recording could not be loaded. Try downloading it instead.');
          }}
        />

        <div className={`audio-player__visualizer${isPlaying ? ' is-playing' : ''}`} aria-hidden="true">
          {VISUALIZER_BARS.map((height, index) => (
            <i key={`${height}-${index}`} style={{ height: `${height}%`, animationDelay: `${index * 45}ms` }} />
          ))}
        </div>

        <div className="audio-player__meta">
          <div>
            <Text strong>{call.phone_number || 'Unknown number'}</Text>
            <Text type="secondary">{call.agent_name || call.agent_user || 'Unknown agent'} · {call.project_name || 'Unmapped project'}</Text>
          </div>
          <Tag color={isPlaying ? 'processing' : 'default'}>{isBuffering ? 'Buffering' : isPlaying ? 'Playing' : 'Ready'}</Tag>
        </div>

        <div className="audio-player__timeline">
          <Slider
            min={0}
            max={duration || 0}
            step={0.1}
            value={Math.min(currentTime, duration || 0)}
            onChange={seek}
            tooltip={{ open: false }}
            aria-label="Recording position"
          />
          <div className="audio-player__times">
            <span>{formatTime(currentTime)}</span>
            <span>-{formatTime(Math.max(duration - currentTime, 0))}</span>
          </div>
        </div>

        <div className="audio-player__controls">
          <div className="audio-player__volume">
            <Button
              type="text"
              shape="circle"
              icon={muted || volume === 0 ? <AudioMutedOutlined /> : <SoundOutlined />}
              onClick={toggleMute}
              aria-label={muted ? 'Unmute recording' : 'Mute recording'}
            />
            <Slider min={0} max={1} step={0.01} value={muted ? 0 : volume} onChange={changeVolume} tooltip={{ open: false }} aria-label="Volume" />
          </div>

          <div className="audio-player__transport">
            <Button type="text" shape="circle" icon={<BackwardOutlined />} onClick={() => skip(-10)} aria-label="Back 10 seconds" />
            <Button
              className="audio-player__play"
              type="primary"
              shape="circle"
              size="large"
              loading={isBuffering}
              icon={isPlaying ? <PauseOutlined /> : <PlayCircleFilled />}
              onClick={() => void togglePlayback()}
              aria-label={isPlaying ? 'Pause recording' : 'Play recording'}
            />
            <Button type="text" shape="circle" icon={<ForwardOutlined />} onClick={() => skip(10)} aria-label="Forward 10 seconds" />
          </div>

          <div className="audio-player__tools">
            <Select
              value={playbackRate}
              onChange={changePlaybackRate}
              options={PLAYBACK_RATES.map((rate) => ({ value: rate, label: `${rate}×` }))}
              aria-label="Playback speed"
              popupMatchSelectWidth={false}
            />
            <Button href={`${recordingUrl}?download=1`} icon={<DownloadOutlined />} aria-label="Download recording" />
          </div>
        </div>

        {error && <Text className="audio-player__error" type="danger" role="alert">{error}</Text>}
      </div>
  );
}

export function AudioPlayerModal({ call, onClose }: AudioPlayerModalProps) {
  return (
    <Modal
      open={Boolean(call)}
      onCancel={onClose}
      footer={null}
      centered
      width={640}
      destroyOnHidden
      title={(
        <div className="audio-modal__title">
          <span className="audio-modal__title-icon"><CustomerServiceOutlined /></span>
          <span>
            <Title level={4}>Call recording</Title>
            <Text type="secondary">Call {call?.call_id || '—'} · Lead {call?.lead_id || '—'}</Text>
          </span>
        </div>
      )}
      classNames={{ container: 'audio-modal__content', header: 'audio-modal__header', body: 'audio-modal__body', close: 'audio-modal__close' }}
    >
      {call && <AudioPlayer call={call} />}
    </Modal>
  );
}
