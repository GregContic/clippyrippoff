import { useEffect, useRef } from 'react';
import type { Candidate } from '../api/types';
import { formatClock } from '../lib/format';
import { Button, Card } from './ui';

export function PreviewModal({
  candidate,
  previewUrl,
  onClose,
}: {
  candidate: Candidate | null;
  previewUrl?: string | null;
  onClose: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    if (!candidate || !videoRef.current) {
      return;
    }
    const video = videoRef.current;
    const handleLoaded = () => {
      if (candidate.start > 0) {
        video.currentTime = candidate.start;
      }
    };
    video.addEventListener('loadedmetadata', handleLoaded);
    return () => video.removeEventListener('loadedmetadata', handleLoaded);
  }, [candidate]);

  if (!candidate) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm" onClick={onClose} role="presentation">
      <Card className="w-full max-w-4xl overflow-hidden" onClick={(event) => event.stopPropagation()}>
        <div className="grid gap-0 lg:grid-cols-[1.4fr_1fr]">
          <div className="bg-black">
            {previewUrl ? (
              <video ref={videoRef} src={previewUrl} controls className="h-full w-full max-h-[70vh] bg-black object-contain" />
            ) : (
              <div className="flex min-h-[40vh] items-center justify-center text-sm text-slate-500">Preview unavailable</div>
            )}
          </div>
          <div className="space-y-5 p-5">
            <div>
              <div className="text-xs uppercase tracking-[0.28em] text-slate-500">Candidate #{String(candidate.id).padStart(2, '0')}</div>
              <h3 className="mt-2 text-xl font-semibold text-white">{formatClock(candidate.start)} → {formatClock(candidate.end)}</h3>
              <p className="mt-2 text-sm text-slate-400">Score {candidate.candidate_score} • {candidate.audio_level} audio • {candidate.end_reason ?? 'no end reason'}</p>
            </div>
            <div className="space-y-2 text-sm text-slate-300">
              <div>Triggers: {candidate.trigger_types.join(', ') || '—'}</div>
              <div>Keywords: {candidate.matched_keywords.join(', ') || '—'}</div>
              <div>Transcript: {candidate.transcript ?? '—'}</div>
            </div>
            <Button type="button" variant="secondary" onClick={onClose} className="w-full">
              Close
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
