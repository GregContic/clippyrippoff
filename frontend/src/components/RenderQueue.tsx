import type { RenderJob } from '../api/types';
import { formatDate } from '../lib/format';
import { Button, Card, EmptyState } from './ui';

const statusTone: Record<string, string> = {
  queued: 'queued',
  running: 'running',
  completed: 'completed',
  failed: 'failed',
};

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
        const openUrl = job.output_url ?? (job.output_path ? `/media/shorts/${job.output_path.split(/[/\\]/).pop() ?? ''}` : null);
        return (
          <Card key={job.id} className="p-5">
            <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
              <div>
                <div className="text-sm text-slate-400">Candidate #{job.candidate_id ?? '—'}</div>
                <div className="mt-1 text-lg font-semibold text-white">{job.message ?? 'Rendering...'}</div>
                <div className="mt-2 text-sm text-slate-500">{job.stage ?? job.status} • {formatDate(job.created_at)}</div>
                {job.error ? <div className="mt-3 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">{job.error}</div> : null}
              </div>

              <div className="flex flex-wrap gap-2">
                {openUrl && job.status === 'completed' ? (
                  <a href={openUrl} target="_blank" rel="noreferrer" className="inline-flex items-center justify-center rounded-xl border border-slate-700 bg-slate-800/80 px-4 py-2 text-sm font-semibold text-slate-100 transition hover:border-sky-400/40 hover:bg-slate-700/80">
                    View
                  </a>
                ) : null}
                <Button type="button" variant="danger" onClick={() => onRemove(job.id)} disabled={job.status === 'running'}>
                  Remove from queue
                </Button>
              </div>
            </div>

            <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-800">
              <div className={`h-full rounded-full ${statusTone[job.status] ? 'bg-cyan-400' : 'bg-sky-400'}`} style={{ width: job.status === 'completed' ? '100%' : job.status === 'running' ? '66%' : '18%' }} />
            </div>
          </Card>
        );
      })}
    </div>
  );
}
