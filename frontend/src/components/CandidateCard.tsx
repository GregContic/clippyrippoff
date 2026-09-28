import type { Candidate } from '../api/types';
import { formatClock, formatDuration } from '../lib/format';
import { Button, Card, Badge } from './ui';

export function CandidateCard({
  candidate,
  selected,
  onToggle,
  onPreview,
}: {
  candidate: Candidate;
  selected: boolean;
  onToggle: () => void;
  onPreview: () => void;
}) {
  return (
    <Card className={`overflow-hidden transition ${selected ? 'border-sky-400/50 ring-1 ring-sky-400/25' : 'border-slate-800'}`}>
      <div className="aspect-video bg-gradient-to-br from-slate-800 to-slate-950 p-4">
        <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-slate-700 bg-slate-950/40 text-center text-sm text-slate-500">
          VIDEO PREVIEW
        </div>
      </div>
      <div className="space-y-4 p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-base font-semibold text-white">#{String(candidate.id).padStart(2, '0')} • {formatDuration(candidate.duration)}</div>
            <div className="mt-1 text-sm text-slate-400">Score: {candidate.candidate_score}</div>
          </div>
          <label className="inline-flex items-center gap-2 rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-300">
            <input type="checkbox" checked={selected} onChange={onToggle} className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-sky-500 focus:ring-sky-400" />
            Selected
          </label>
        </div>

        <div className="flex flex-wrap gap-2">
          {candidate.trigger_types.map((trigger) => (
            <Badge key={trigger} variant="idle">
              {trigger}
            </Badge>
          ))}
        </div>

        <div className="space-y-2 text-sm text-slate-300">
          <div className="flex justify-between gap-4"><span className="text-slate-500">Start</span><span>{formatClock(candidate.start)}</span></div>
          <div className="flex justify-between gap-4"><span className="text-slate-500">End</span><span>{formatClock(candidate.end)}</span></div>
          <div className="flex justify-between gap-4"><span className="text-slate-500">End reason</span><span>{candidate.end_reason ?? '—'}</span></div>
        </div>

        {candidate.transcript ? <p className="line-clamp-3 text-sm leading-6 text-slate-400">{candidate.transcript}</p> : null}

        <div className="flex gap-2">
          <Button type="button" variant="secondary" onClick={onPreview} className="flex-1">
            Preview
          </Button>
          <Button type="button" variant={selected ? 'primary' : 'secondary'} onClick={onToggle} className="flex-1">
            {selected ? 'Selected' : 'Select'}
          </Button>
        </div>
      </div>
    </Card>
  );
}
