import type { BatchResponse } from '../api/types';
import { resolveMediaUrl } from '../api/client';
import { Button, Card } from './ui';

const statusLabels: Record<string, string> = {
  queued: 'Queued',
  running: 'Running',
  completed: 'Completed',
  partially_completed: 'Partially completed',
  failed: 'Failed',
  interrupted: 'Interrupted',
};

export function BatchProgress({
  batch,
  pollingError,
  onRetryPolling,
}: {
  batch: BatchResponse;
  pollingError?: string | null;
  onRetryPolling?: () => void;
}) {
  const completed = batch.children.filter((child) => child.status === 'completed').length;
  const failed = batch.children.filter((child) => child.status === 'failed').length;
  const interrupted = batch.children.filter((child) => child.status === 'interrupted').length;
  const status = statusLabels[batch.status] ?? batch.status.replace(/_/g, ' ');
  const percent = Math.max(0, Math.min(100, batch.percent));

  return (
    <Card className="space-y-3 p-4" role="region" aria-label="Batch progress">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="font-semibold text-white">Batch Clips progress</h3>
          <p className="text-sm text-slate-300" aria-live="polite">
            {status} · {Math.round(percent)}% · {completed}/{batch.children.length} clips completed
            {failed ? ` · ${failed} failed` : ''}
            {interrupted ? ` · ${interrupted} interrupted` : ''}
          </p>
        </div>
        {onRetryPolling ? (
          <Button type="button" variant="secondary" onClick={onRetryPolling}>
            Refresh status
          </Button>
        ) : null}
      </div>
      <div
        className="h-2 overflow-hidden rounded-full bg-surface-700"
        role="progressbar"
        aria-label="Batch completion"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(percent)}
      >
        <div className="h-full rounded-full bg-accent-400 transition-[width]" style={{ width: `${percent}%` }} />
      </div>
      {pollingError ? (
        <p className="text-sm text-danger-100" role="alert">
          Could not refresh batch status: {pollingError} The app will retry automatically.
        </p>
      ) : null}
      {batch.children.length ? (
        <ul className="grid gap-2 sm:grid-cols-2" aria-label="Batch clips">
          {batch.children.map((child) => (
            <li key={child.job_id} className="rounded-xl border border-surface-700 bg-surface-800 p-3 text-sm">
              <div className="flex justify-between gap-2 text-slate-200">
                <span>Candidate #{child.candidate_id ?? '?'}</span>
                <span>{statusLabels[child.status] ?? child.status.replace(/_/g, ' ')} · {Math.round(child.percent)}%</span>
              </div>
              {child.output_url ? (
                <a
                  className="mt-2 inline-block text-sky-300 underline underline-offset-4 hover:text-sky-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-400"
                  href={resolveMediaUrl(child.output_url) ?? child.output_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open clip
                </a>
              ) : null}
              {child.error ? <p className="mt-1 text-danger-100">{child.error}</p> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </Card>
  );
}
