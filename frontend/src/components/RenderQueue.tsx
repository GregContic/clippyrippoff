import type { RenderJob } from '../api/types';
import { resolveMediaUrl, retryRender } from '../api/client';
import { formatDate } from '../lib/format';
import { Button, Card, EmptyState } from './ui';

export function RenderQueue({
  jobs,
  onRemove,
}: {
  jobs: RenderJob[];
  onRemove: (jobId: string) => void;
}) {
  if (!jobs.length) {
    return <EmptyState title="Render queue is empty" description="Submitted clip renders will appear here." />;
  }

  return (
    <div className="grid gap-4">
      {jobs.map((job) => {
        const openUrl = resolveMediaUrl(job.output_url ?? (job.output_path ? `/media/shorts/${job.output_path.split(/[/\\]/).pop() ?? ''}` : null));
        const snapshot = job.result && typeof job.result === 'object' ? (job.result as { request_signature?: any }).request_signature : null;
        return (
          <Card key={job.id} className="p-5">
            <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
              <div>
                <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Candidate #{job.candidate_id ?? '—'}</div>
                <div className="mt-1 text-lg font-semibold text-white">{job.message ?? 'Rendering...'}</div>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-slate-500">
                  <span>{job.stage ?? job.status}</span>
                  <span>•</span>
                  <span>{formatDate(job.created_at)}</span>
                  {job.retry_of ? <span>• retry of {job.retry_of.slice(0, 8)}</span> : null}
                  <span className={`rounded-full border px-2 py-0.5 text-[11px] uppercase tracking-[0.18em] ${job.status === 'running' ? 'border-warning-500/30 bg-warning-500/10 text-warning-200' : job.status === 'completed' ? 'border-success-500/30 bg-success-500/10 text-success-100' : job.status === 'failed' || job.status === 'interrupted' ? 'border-danger-500/30 bg-danger-500/10 text-danger-100' : 'border-accent-500/30 bg-accent-500/10 text-accent-300'}`}>
                    {job.status}
                  </span>
                </div>
                {job.error ? <div className="mt-3 rounded-xl border border-danger-500/30 bg-danger-500/10 px-3 py-2 text-sm text-danger-100">{job.error}</div> : null}
                {snapshot ? (
                  <div className="mt-3 grid gap-2 rounded-xl border border-surface-700 bg-surface-800 p-3 text-xs text-slate-400 sm:grid-cols-2">
                    <div>Trim: {typeof snapshot.start === 'number' && typeof snapshot.end === 'number' ? `${snapshot.start.toFixed(2)}s → ${snapshot.end.toFixed(2)}s` : '—'}</div>
                    <div>Captions: {snapshot.render_settings?.captions_enabled === false ? 'Disabled' : 'Enabled'}</div>
                    <div>Output: {snapshot.render_settings?.output_width ?? '—'} × {snapshot.render_settings?.output_height ?? '—'} @ {snapshot.render_settings?.fps ?? '—'}</div>
                    <div>Audio normalization: {snapshot.render_settings?.normalize_audio === false ? 'Off' : 'On'}</div>
                  </div>
                ) : null}
              </div>

              <div className="flex flex-wrap gap-2">
                {openUrl && job.status === 'completed' ? (
                  <a href={openUrl} target="_blank" rel="noreferrer" className="inline-flex items-center justify-center rounded-xl border border-surface-600 bg-surface-800 px-4 py-2 text-sm font-medium text-slate-100 transition hover:border-accent-500/40 hover:bg-surface-700">
                    View
                  </a>
                ) : null}
                {job.status === 'failed' || job.status === 'interrupted' ? (
                  <Button type="button" variant="secondary" onClick={() => { void retryRender(job.id).then(() => window.location.reload()).catch(() => undefined); }}>
                    Retry
                  </Button>
                ) : null}
                <Button type="button" variant="danger" onClick={() => onRemove(job.id)} disabled={job.status === 'running'}>
                  Remove from queue
                </Button>
              </div>
            </div>

            <div className="mt-4 h-2 overflow-hidden rounded-full bg-surface-800">
              <div className={`h-full rounded-full ${job.status === 'running' ? 'bg-warning-500' : job.status === 'completed' ? 'bg-success-500' : job.status === 'failed' || job.status === 'interrupted' ? 'bg-danger-500' : 'bg-accent-500'}`} style={{ width: job.percent != null ? `${Math.max(0, Math.min(100, job.percent))}%` : '100%' }} aria-hidden="true" />
            </div>
          </Card>
        );
      })}
    </div>
  );
}
