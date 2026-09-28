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
  const savedStart = candidate.trim_start ?? candidate.start;
  const savedEnd = candidate.trim_end ?? candidate.end;
  const effectiveDuration = Math.max(savedEnd - savedStart, 0);
  return (
    <Card className={`overflow-hidden transition ${selected ? 'border-accent-500/40 ring-1 ring-accent-500/20' : ''}`}>
      <div className="aspect-video bg-surface-800 p-4">
        <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-surface-600 bg-surface-900 text-center text-sm text-slate-500">
          Video preview
        </div>
      </div>
      <div className="space-y-4 p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-base font-semibold text-white">#{String(candidate.id).padStart(2, '0')} • {formatDuration(candidate.duration)}</div>
            <div className="mt-1 text-sm text-slate-400">Score: {candidate.candidate_score}</div>
            <div className="mt-1 text-xs text-slate-500">Effective duration: {formatDuration(effectiveDuration)}</div>
          </div>
          <label className="inline-flex items-center gap-2 rounded-full border border-surface-600 bg-surface-800 px-3 py-1 text-xs text-slate-300">
            <input type="checkbox" checked={selected} onChange={onToggle} className="h-4 w-4 rounded border-surface-600 bg-surface-900 text-accent-500 focus:ring-accent-400" />
            Selected
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

        <div className="space-y-2 text-sm text-slate-300">
          <div className="flex justify-between gap-4"><span className="text-slate-500">Start</span><span>{formatClock(candidate.start)}</span></div>
          <div className="flex justify-between gap-4"><span className="text-slate-500">End</span><span>{formatClock(candidate.end)}</span></div>
          <div className="flex justify-between gap-4"><span className="text-slate-500">Saved trim</span><span>{candidate.trim_saved ? `${formatClock(savedStart)} → ${formatClock(savedEnd)}` : '—'}</span></div>
          <div className="flex justify-between gap-4"><span className="text-slate-500">End reason</span><span>{candidate.end_reason ?? '—'}</span></div>
        </div>

        {candidate.transcript ? <p className="line-clamp-3 text-sm leading-6 text-slate-400">{candidate.transcript}</p> : null}

        <div className="flex gap-2">
          <Button type="button" variant="secondary" onClick={onPreview} className="flex-1">
            Preview
          </Button>
          <Button type="button" variant="secondary" onClick={onEdit} className="flex-1">
            Trim
          </Button>
          <Button type="button" variant={selected ? 'primary' : 'secondary'} onClick={onToggle} className="flex-1">
            {selected ? 'Selected' : 'Select'}
          </Button>
        </div>
      </div>
    </Card>
  );
}
