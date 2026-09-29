import { useEffect, useRef, useState } from 'react';
import { resolveMediaUrl } from '../api/client';
import type { Candidate } from '../api/types';
import { formatClock, formatDuration } from '../lib/format';
import { Button, Card, Badge } from './ui';

export function CandidateCard({
  candidate,
  selected,
  onToggle,
  onPreview,
  onEdit,
  renderStatus,
}: {
  candidate: Candidate;
  selected: boolean;
  onToggle: () => void;
  onPreview: () => void;
  onEdit: () => void;
  renderStatus?: string | null;
}) {
  const previewContainerRef = useRef<HTMLDivElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [previewReady, setPreviewReady] = useState(false);
  const [previewFailed, setPreviewFailed] = useState(false);
  const savedStart = candidate.trim_start ?? candidate.start;
  const savedEnd = candidate.trim_end ?? candidate.end;
  const effectiveDuration = Math.max(savedEnd - savedStart, 0);
  const previewUrl = resolveMediaUrl(candidate.preview_url);

  useEffect(() => {
    const container = previewContainerRef.current;
    if (!container || !previewUrl) {
      return;
    }
    if (!('IntersectionObserver' in window)) {
      setPreviewReady(true);
      return;
    }
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setPreviewReady(true);
        observer.disconnect();
      }
    }, { rootMargin: '240px 0px' });
    observer.observe(container);
    return () => observer.disconnect();
  }, [previewUrl]);

  function seekToCandidate(video: HTMLVideoElement) {
    const start = Math.max(savedStart, 0);
    const end = Math.max(savedEnd, start);
    video.currentTime = Math.min(Math.max(video.currentTime || start, start), end);
  }

  return (
    <Card className={`flex h-full flex-col overflow-hidden transition ${selected ? 'border-accent-500/40 ring-1 ring-accent-500/20' : ''}`}>
      <div ref={previewContainerRef} className="aspect-[16/8] bg-surface-800 p-3">
        {previewUrl && previewReady && !previewFailed ? (
          <video
            ref={videoRef}
            src={previewUrl}
            controls
            preload="metadata"
            playsInline
            aria-label={`Preview for candidate ${candidate.id}`}
            className="h-full w-full rounded-xl border border-surface-600 bg-surface-950 object-contain"
            onLoadedMetadata={(event) => seekToCandidate(event.currentTarget)}
            onPlay={(event) => seekToCandidate(event.currentTarget)}
            onTimeUpdate={(event) => {
              const video = event.currentTarget;
              if (video.currentTime >= savedEnd) {
                video.pause();
                video.currentTime = savedStart;
              }
            }}
            onError={() => setPreviewFailed(true)}
          />
        ) : (
          <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-surface-600 bg-surface-900 px-4 text-center text-sm text-slate-500">
            {previewUrl ? (previewFailed ? 'Preview unavailable' : 'Loading preview...') : 'No preview media available'}
          </div>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-base font-semibold text-white">#{String(candidate.id).padStart(2, '0')} <span className="text-slate-500">•</span> {formatDuration(candidate.duration)}</div>
            <div className="mt-1 text-sm text-slate-400">Score: {candidate.candidate_score} <span className="text-slate-600">•</span> Effective: {formatDuration(effectiveDuration)}</div>
          </div>
          <label className={`inline-flex shrink-0 cursor-pointer items-center gap-2 rounded-full border px-3 py-1 text-xs ${selected ? 'border-accent-500/40 bg-accent-500/10 text-accent-200' : 'border-surface-600 bg-surface-800 text-slate-300'}`}>
            <input type="checkbox" aria-label={`${selected ? 'Deselect' : 'Select'} candidate ${candidate.id}`} checked={selected} onChange={onToggle} className="h-4 w-4 rounded border-surface-600 bg-surface-900 text-accent-500 focus:ring-accent-400" />
            {selected ? 'Selected' : 'Select'}
          </label>
        </div>

        <div className="flex flex-wrap gap-2">
          {candidate.trim_saved ? (
            <Badge variant="local">Trim saved</Badge>
          ) : null}
          {renderStatus ? <Badge variant={renderStatus === 'completed' ? 'completed' : renderStatus === 'running' ? 'running' : renderStatus === 'failed' || renderStatus === 'interrupted' ? 'failed' : 'queued'}>{renderStatus}</Badge> : null}
          {candidate.trigger_types.map((trigger) => (
            <Badge key={trigger} variant="neutral">
              {trigger}
            </Badge>
          ))}
        </div>

        <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-sm text-slate-300">
          <span className="text-slate-500">Start</span><span className="text-right tabular-nums">{formatClock(candidate.start)}</span>
          <span className="text-slate-500">End</span><span className="text-right tabular-nums">{formatClock(candidate.end)}</span>
          <span className="text-slate-500">Saved trim</span><span className="truncate text-right tabular-nums">{candidate.trim_saved ? `${formatClock(savedStart)} → ${formatClock(savedEnd)}` : '—'}</span>
          <span className="text-slate-500">End reason</span><span className="truncate text-right">{candidate.end_reason ?? '—'}</span>
        </div>

        {candidate.transcript ? (
          <div className="text-sm text-slate-400">
            <p className="line-clamp-3 leading-5">{candidate.transcript}</p>
            <details className="mt-1">
              <summary className="cursor-pointer list-inside text-xs text-slate-300 marker:text-slate-500">View full transcript</summary>
              <p className="mt-1 leading-5">{candidate.transcript}</p>
            </details>
          </div>
        ) : null}

        <div className="mt-auto flex gap-2 pt-1">
          <Button type="button" variant="secondary" onClick={onPreview} className="flex-1">
            Preview
          </Button>
          <Button type="button" variant="secondary" onClick={onEdit} className="flex-1">
            Trim
          </Button>
        </div>
      </div>
    </Card>
  );
}
