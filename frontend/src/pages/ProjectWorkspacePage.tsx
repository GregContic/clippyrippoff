import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  analyzeVideo,
  deleteRender,
  deleteLibraryFile,
  getCandidates,
  getProject,
  getProjectFiles,
  getProjectRenders,
  renderCandidateOverride,
  renderCandidates,
  resolveMediaUrl,
} from '../api/client';
import type { Candidate, CandidateEditorState, ProjectFileItem, ProjectSummary, RenderJob } from '../api/types';
import { AnalysisProgress } from '../components/AnalysisProgress';
import { CandidateEditorModal } from '../components/CandidateEditorModal';
import { CandidateGrid } from '../components/CandidateGrid';
import { PreviewModal } from '../components/PreviewModal';
import { RenderQueue } from '../components/RenderQueue';
import { Button, Card, EmptyState } from '../components/ui';
import { formatBytes, formatDate, formatDuration } from '../lib/format';

type TabKey = 'overview' | 'candidates' | 'renders' | 'files';

const tabs: Array<{ key: TabKey; label: string }> = [
  { key: 'overview', label: 'Overview' },
  { key: 'candidates', label: 'Candidates' },
  { key: 'renders', label: 'Renders' },
  { key: 'files', label: 'Files' },
];

export function ProjectWorkspacePage() {
  const { videoId = '' } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [activeCandidate, setActiveCandidate] = useState<Candidate | null>(null);
  const [editingCandidate, setEditingCandidate] = useState<Candidate | null>(null);
  const [renderJobs, setRenderJobs] = useState<RenderJob[]>([]);
  const [projectFiles, setProjectFiles] = useState<ProjectFileItem[]>([]);
  const [sourceDuration, setSourceDuration] = useState<number | null>(null);
  const [transcriptUrl, setTranscriptUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rendering, setRendering] = useState(false);
  const [busyAction, setBusyAction] = useState<'analyze' | 'refresh' | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>('overview');
  const [candidateScoreMin, setCandidateScoreMin] = useState('');
  const [candidateDurationMin, setCandidateDurationMin] = useState('');
  const [candidateRenderStatus, setCandidateRenderStatus] = useState('all');

  async function loadWorkspace() {
    try {
      const [summary, renderResponse, fileResponse] = await Promise.all([
        getProject(videoId),
        getProjectRenders(videoId).catch(() => []),
        getProjectFiles(videoId).catch(() => ({ items: [] })),
      ]);
      setProject(summary);
      setTranscriptUrl(summary.transcript_url ?? null);
      setRenderJobs(renderResponse);
      setProjectFiles(fileResponse.items);
      setError(null);
      if (summary.status === 'completed' && summary.candidate_count > 0) {
        const candidateResponse = await getCandidates(videoId);
        setCandidates(candidateResponse.candidates);
        setSourceDuration(candidateResponse.source_duration ?? summary.source_duration ?? null);
      } else {
        setCandidates([]);
        setSourceDuration(summary.source_duration ?? null);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to load project workspace.');
    }
  }

  useEffect(() => {
    let active = true;
    void loadWorkspace().then(() => {
      if (!active) {
        return;
      }
    });
    const interval = window.setInterval(() => {
      if (active) {
        void loadWorkspace();
      }
    }, 3000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId]);

  const renderStatusByCandidateId = useMemo(() => {
    const map: Record<number, string> = {};
    [...renderJobs].sort((a, b) => (b.updated_at ?? b.created_at).localeCompare(a.updated_at ?? a.created_at)).forEach((job) => {
      if (job.candidate_id != null && !map[job.candidate_id]) {
        map[job.candidate_id] = job.status;
      }
    });
    return map;
  }, [renderJobs]);

  const filteredCandidates = useMemo(() => {
    const scoreMin = Number(candidateScoreMin);
    const durationMin = Number(candidateDurationMin);
    return candidates.filter((candidate) => {
      if (candidateRenderStatus !== 'all' && (renderStatusByCandidateId[candidate.id] ?? 'none') !== candidateRenderStatus) {
        return false;
      }
      if (candidateScoreMin.trim() && Number.isFinite(scoreMin) && candidate.candidate_score < scoreMin) {
        return false;
      }
      if (candidateDurationMin.trim() && Number.isFinite(durationMin) && candidate.duration < durationMin) {
        return false;
      }
      return true;
    });
  }, [candidateDurationMin, candidateRenderStatus, candidateScoreMin, candidates, renderStatusByCandidateId]);

  function toggleCandidate(candidateId: number) {
    setSelectedIds((current) => (current.includes(candidateId) ? current.filter((id) => id !== candidateId) : [...current, candidateId]));
  }

  function selectAll() {
    setSelectedIds(filteredCandidates.map((candidate) => candidate.id));
  }

  function clearSelection() {
    setSelectedIds([]);
  }

  async function renderSelected() {
    if (!selectedIds.length) {
      return;
    }
    setRendering(true);
    setError(null);
    try {
      await renderCandidates(videoId, selectedIds);
      setActiveTab('renders');
      await loadWorkspace();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to submit render jobs.');
    } finally {
      setRendering(false);
    }
  }

  async function renderTrim(candidate: Candidate, start: number, end: number, state: CandidateEditorState) {
    setRendering(true);
    setError(null);
    try {
      await renderCandidateOverride(videoId, [candidate.id], { [String(candidate.id)]: { start, end } }, { [String(candidate.id)]: state });
      setActiveTab('renders');
      await loadWorkspace();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to submit render job.');
    } finally {
      setRendering(false);
    }
  }

  async function handleAnalyze(forceDownload: boolean) {
    if (!project?.url) {
      return;
    }
    setBusyAction('analyze');
    setError(null);
    try {
      const response = await analyzeVideo(project.url, forceDownload);
      navigate(`/projects/${response.video_id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to start analysis.');
    } finally {
      setBusyAction(null);
    }
  }

  async function handleRemoveFile(filename: string) {
    if (!window.confirm(`Delete ${filename}? This only removes the rendered clip.`)) {
      return;
    }
    setBusyAction('refresh');
    try {
      await deleteLibraryFile(filename);
      await loadWorkspace();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to delete the rendered clip.');
    } finally {
      setBusyAction(null);
    }
  }

  const completedRenderJobs = renderJobs.filter((job) => job.status === 'completed');
  const interruptedRenderJobs = renderJobs.filter((job) => job.status === 'interrupted');
  const failedRenderJobs = renderJobs.filter((job) => job.status === 'failed');
  const queuedRenderJobs = renderJobs.filter((job) => job.status === 'queued' || job.status === 'running');

  if (!project) {
    return <Card className="p-6 text-sm text-slate-400">Loading project workspace...</Card>;
  }

  return (
    <div className="space-y-6">
      <Card className="overflow-hidden p-0">
        <div className="grid gap-0 lg:grid-cols-[1.2fr_0.8fr]">
          <div className="min-w-0 p-5 sm:p-6">
            <div className="flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.22em] text-slate-500">
              <span>{project.source_cache_status ?? 'cache unknown'}</span>
              <span>•</span>
              <span>{project.video_id}</span>
            </div>
            <div className="mt-3 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0 space-y-2">
                <h2 className="break-words text-2xl font-semibold tracking-tight text-white sm:text-3xl">{project.title ?? project.video_id}</h2>
                <p className="max-w-2xl text-sm leading-6 text-slate-400">{project.message ?? 'Local project workspace for candidates, renders, and generated clips.'}</p>
                <dl className="grid max-w-2xl grid-cols-2 gap-x-5 gap-y-2 text-xs sm:grid-cols-4">
                  <div><dt className="text-slate-500">Status</dt><dd className="mt-0.5 truncate text-slate-200">{project.status}</dd></div>
                  <div><dt className="text-slate-500">Candidates</dt><dd className="mt-0.5 text-slate-200">{project.candidate_count}</dd></div>
                  <div><dt className="text-slate-500">Rendered</dt><dd className="mt-0.5 text-slate-200">{project.rendered_count}</dd></div>
                  <div><dt className="text-slate-500">Source duration</dt><dd className="mt-0.5 text-slate-200">{project.source_duration != null ? formatDuration(project.source_duration) : 'unknown'}</dd></div>
                  <div><dt className="text-slate-500">Manual trims</dt><dd className="mt-0.5 text-slate-200">{project.manual_trim_count ?? 0}</dd></div>
                </dl>
              </div>
              <div className="flex shrink-0 flex-wrap gap-2 sm:max-w-[15rem] sm:justify-end">
                <Button type="button" variant="secondary" onClick={() => navigate('/')}>Back to Projects</Button>
                <Button type="button" variant="secondary" onClick={() => void handleAnalyze(false)} disabled={busyAction === 'analyze'}>Analyze</Button>
                <Button type="button" onClick={() => void handleAnalyze(true)} disabled={busyAction === 'analyze'}>Re-analyze</Button>
              </div>
            </div>

            <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-slate-400">
              {project.url ? <a href={project.url} target="_blank" rel="noreferrer" className="text-sky-300 underline decoration-sky-400/50 underline-offset-4">Open source on YouTube</a> : <span>Original URL unavailable</span>}
              {project.latest_activity_at ? <span>Latest activity {formatDate(project.latest_activity_at)}</span> : null}
              {project.project_created_at ? <span>Created {formatDate(project.project_created_at)}</span> : null}
              {project.last_analyzed_at ? <span>Analyzed {formatDate(project.last_analyzed_at)}</span> : null}
            </div>
          </div>

          <div className="border-t border-slate-800 bg-slate-950/60 p-4 lg:border-l lg:border-t-0">
            {project.source_thumbnail_url ? (
              <div className="aspect-video overflow-hidden rounded-2xl border border-slate-800 bg-black">
                <img src={resolveMediaUrl(project.source_thumbnail_url) ?? project.source_thumbnail_url} alt={project.title ?? project.video_id} className="h-full w-full object-cover" />
              </div>
            ) : (
              <div className="flex aspect-video items-center justify-center rounded-2xl border border-dashed border-slate-800 bg-slate-950/60 text-sm uppercase tracking-[0.24em] text-slate-500">No thumbnail available</div>
            )}
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <MetricCard label="Queued / Running" value={String(queuedRenderJobs.length)} />
              <MetricCard label="Failed / Interrupted" value={String(failedRenderJobs.length + interruptedRenderJobs.length)} />
              <MetricCard label="Completed renders" value={String(completedRenderJobs.length)} />
              <MetricCard label="Saved state" value={project.saved_editing_state ? 'Yes' : 'No'} />
            </div>
          </div>
        </div>
      </Card>

      {project.status !== 'completed' ? <AnalysisProgress stage={project.analysis_stage} message={project.message} status={project.status} /> : null}

      {error ? <Card className="border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-100">{error}</Card> : null}

      <div className="flex flex-wrap gap-2">
        {tabs.map((tab) => (
          <Button key={tab.key} type="button" variant={activeTab === tab.key ? 'primary' : 'secondary'} onClick={() => setActiveTab(tab.key)}>
            {tab.label}
          </Button>
        ))}
      </div>

      {activeTab === 'overview' ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <OverviewMetric label="Candidates" value={String(project.candidate_count)} />
          <OverviewMetric label="Saved trims" value={String(project.manual_trim_count ?? 0)} />
          <OverviewMetric label="Outputs" value={String(project.generated_output_count ?? project.rendered_count)} />
          <OverviewMetric label="Source cache" value={project.source_cache_status ?? 'unknown'} />
          <OverviewMetric label="Queued" value={String(project.queued_render_jobs ?? queuedRenderJobs.length)} />
          <OverviewMetric label="Running" value={String(project.running_render_jobs ?? 0)} />
          <OverviewMetric label="Failed" value={String(project.failed_render_jobs ?? failedRenderJobs.length)} />
          <OverviewMetric label="Interrupted" value={String(project.interrupted_render_jobs ?? interruptedRenderJobs.length)} />
        </div>
      ) : null}

      {activeTab === 'candidates' ? (
        <div className="space-y-4">
          <Card className="grid gap-3 p-4 md:grid-cols-4">
            <label className="space-y-1 text-sm text-slate-300">
              <span className="text-xs uppercase tracking-[0.22em] text-slate-500">Min score</span>
              <input value={candidateScoreMin} onChange={(event) => setCandidateScoreMin(event.target.value)} type="number" min="0" className="w-full rounded-xl border border-slate-800 bg-slate-950/80 px-3 py-2 text-sm text-white" placeholder="0" />
            </label>
            <label className="space-y-1 text-sm text-slate-300">
              <span className="text-xs uppercase tracking-[0.22em] text-slate-500">Min duration</span>
              <input value={candidateDurationMin} onChange={(event) => setCandidateDurationMin(event.target.value)} type="number" min="0" step="0.1" className="w-full rounded-xl border border-slate-800 bg-slate-950/80 px-3 py-2 text-sm text-white" placeholder="0" />
            </label>
            <label className="space-y-1 text-sm text-slate-300">
              <span className="text-xs uppercase tracking-[0.22em] text-slate-500">Render status</span>
              <select value={candidateRenderStatus} onChange={(event) => setCandidateRenderStatus(event.target.value)} className="w-full rounded-xl border border-slate-800 bg-slate-950/80 px-3 py-2 text-sm text-white">
                <option value="all">All</option>
                <option value="queued">Queued</option>
                <option value="running">Running</option>
                <option value="completed">Completed</option>
                <option value="failed">Failed</option>
                <option value="interrupted">Interrupted</option>
                <option value="none">No render</option>
              </select>
            </label>
            <div className="flex items-end gap-2">
              <Button type="button" variant="secondary" onClick={() => { setCandidateScoreMin(''); setCandidateDurationMin(''); setCandidateRenderStatus('all'); }}>Reset filters</Button>
              <Button type="button" onClick={() => setSelectedIds(filteredCandidates.map((candidate) => candidate.id))} disabled={!filteredCandidates.length}>Select filtered</Button>
            </div>
          </Card>
          {candidates.length ? (
            <CandidateGrid
              candidates={filteredCandidates}
              selectedIds={selectedIds}
              onToggle={toggleCandidate}
              onSelectAll={selectAll}
              onClear={clearSelection}
              onPreview={(candidate) => setActiveCandidate(candidate)}
              onEdit={(candidate) => setEditingCandidate(candidate)}
              onRender={renderSelected}
              busy={rendering}
              renderStatusById={renderStatusByCandidateId}
            />
          ) : (
            <EmptyState title="No candidates available" description="This project has not produced candidates yet or analysis is still running." />
          )}
        </div>
      ) : null}

      {activeTab === 'renders' ? (
        <div className="space-y-4">
          <RenderQueue
            jobs={renderJobs.filter((job) => job.video_id === project.video_id)}
            onRemove={async (renderId) => {
              await deleteRender(renderId).catch(() => undefined);
              await loadWorkspace();
            }}
          />
          {!renderJobs.length ? <EmptyState title="No renders yet" description="Submitted renders for this project will appear here." /> : null}
        </div>
      ) : null}

      {activeTab === 'files' ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {projectFiles.length ? projectFiles.map((file) => (
            <Card key={file.render_job_id ?? file.filename} className="overflow-hidden">
              <div className="bg-black">
                <video src={resolveMediaUrl(file.url) ?? file.url} controls preload="metadata" className="aspect-video w-full bg-black object-cover" />
              </div>
              <div className="space-y-4 p-4">
                <div>
                  <div className="truncate text-sm font-semibold text-white">{file.filename}</div>
                  <div className="mt-1 text-sm text-slate-400">{file.candidate_id != null ? `Candidate #${file.candidate_id}` : 'Candidate unknown'} • {formatDuration(file.duration)} • {formatBytes(file.size_bytes)}</div>
                  <div className="mt-1 text-xs text-slate-500">{formatDate(file.created_at)}</div>
                </div>
                <div className="flex gap-2">
                  <a href={resolveMediaUrl(file.url) ?? file.url} target="_blank" rel="noreferrer" className="inline-flex flex-1 items-center justify-center rounded-xl border border-slate-700 bg-slate-800/80 px-4 py-2 text-sm font-semibold text-slate-100 transition hover:border-sky-400/40 hover:bg-slate-700/80">
                    Play
                  </a>
                  <Button type="button" variant="danger" className="flex-1" onClick={() => void handleRemoveFile(file.filename)}>
                    Delete
                  </Button>
                </div>
              </div>
            </Card>
          )) : <EmptyState title="No rendered clips yet" description="Project outputs will appear here once renders complete." />}
        </div>
      ) : null}

      <PreviewModal candidate={activeCandidate} previewUrl={activeCandidate?.preview_url ?? project.source_video_url ?? null} onClose={() => setActiveCandidate(null)} />
      <CandidateEditorModal
        videoId={videoId}
        candidate={editingCandidate}
        previewUrl={editingCandidate?.preview_url ?? project.source_video_url ?? null}
        transcriptUrl={transcriptUrl}
        sourceDuration={sourceDuration}
        onClose={() => setEditingCandidate(null)}
        onSavedTrim={async (candidate, start, end) => {
          setCandidates((current) => current.map((item) => (item.id === candidate.id ? { ...item, trim_start: start, trim_end: end, trim_saved: true } : item)));
          await loadWorkspace();
        }}
        onRender={renderTrim}
      />
    </div>
  );
}

function OverviewMetric({ label, value }: { label: string; value: string }) {
  return (
    <Card className="p-4">
      <div className="text-xs uppercase tracking-[0.22em] text-slate-500">{label}</div>
      <div className="mt-2 text-lg font-semibold text-white">{value}</div>
    </Card>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-950/50 p-3">
      <div className="text-xs uppercase tracking-[0.22em] text-slate-500">{label}</div>
      <div className="mt-2 text-sm font-semibold text-white">{value}</div>
    </div>
  );
}