import { useState } from 'react';
import type { RenderJob } from '../api/types';
import { resolveMediaUrl, updateRenderReview } from '../api/client';
import { formatDate, formatDuration } from '../lib/format';
import { Button, Card } from './ui';

export function ReviewModal({ job, onClose, onUpdated, onNeedsChanges }: { job: RenderJob | null; onClose: () => void; onUpdated: (job: RenderJob) => void; onNeedsChanges?: (job: RenderJob) => void }) {
  const [notes, setNotes] = useState(job?.review_notes ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!job) return null;
  const renderJob = job;
  const snapshot = (renderJob.result as { request_signature?: Record<string, any> } | null)?.request_signature;
  const sourceUrl = resolveMediaUrl(renderJob.output_url ?? (renderJob.output_path ? `/media/shorts/${renderJob.output_path.split(/[/\\]/).pop()}` : null));
  async function decide(status: RenderJob['review_status']) {
    setBusy(true); setError(null);
    try {
      const updated = await updateRenderReview(renderJob.id, status, notes);
      onUpdated(updated);
      if (status === 'needs_changes') onNeedsChanges?.(updated);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Unable to save review decision.'); }
    finally { setBusy(false); }
  }
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-surface-950/90 p-4" onClick={onClose} role="presentation">
    <Card className="max-h-[94vh] w-full max-w-4xl overflow-auto p-5" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="review-title">
      <div className="flex items-start justify-between gap-4"><div><div className="text-xs uppercase tracking-[0.2em] text-slate-500">Render review</div><h2 id="review-title" className="mt-2 text-2xl font-semibold text-white">Candidate #{job.candidate_id ?? '—'}</h2></div><Button variant="secondary" onClick={onClose}>Close</Button></div>
      {sourceUrl ? <video src={sourceUrl} controls preload="metadata" className="mx-auto mt-5 max-h-[58vh] w-full bg-black object-contain" onError={() => setError('The rendered file could not be played in this browser.')} /> : <div className="mt-5 rounded-xl border border-danger-500/30 bg-danger-500/10 p-5 text-danger-100">Rendered output is missing. Review approval is unavailable.</div>}
      <div className="mt-5 grid gap-3 rounded-xl border border-surface-700 bg-surface-800 p-4 text-sm text-slate-300 sm:grid-cols-2"><div>Project: {job.video_id ?? '—'}</div><div>Completed: {formatDate(job.updated_at)}</div><div>Output: {snapshot?.render_settings?.output_width ?? '—'} × {snapshot?.render_settings?.output_height ?? '—'} @ {snapshot?.render_settings?.fps ?? '—'} FPS</div><div>Duration: {typeof snapshot?.start === 'number' && typeof snapshot?.end === 'number' ? formatDuration(snapshot.end - snapshot.start) : '—'}</div><div>Captions: {snapshot?.render_settings?.captions_enabled === false ? 'Disabled' : 'Enabled'}</div><div>Audio normalization: {snapshot?.render_settings?.normalize_audio === false ? 'Off' : 'On'}</div></div>
      <label className="mt-4 block text-sm text-slate-300">Review notes<textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} className="mt-2 w-full rounded-xl border border-surface-600 bg-surface-900 px-3 py-2 text-slate-100" /></label>
      {error ? <p className="mt-3 text-sm text-danger-100">{error}</p> : null}
      <div className="mt-4 flex flex-wrap gap-2"><Button onClick={() => void decide('approved')} disabled={busy || !sourceUrl}>Approve</Button><Button variant="secondary" onClick={() => void decide('needs_changes')} disabled={busy || !sourceUrl}>Needs changes</Button><Button variant="secondary" onClick={() => void decide('pending_review')} disabled={busy || !sourceUrl}>Reset review</Button>{job.output_path ? <Button variant="secondary" onClick={() => void navigator.clipboard?.writeText(job.output_path ?? '')}>Copy output path</Button> : null}</div>
    </Card>
  </div>;
}