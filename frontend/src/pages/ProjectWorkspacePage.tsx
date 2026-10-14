import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  analyzeVideo,
  createBatch,
  createCompilation,
  deleteRender,
  deleteLibraryFile,
  getCandidates,
  getCompilation,
  getProject,
  getProjectFiles,
  getProjectMusic,
  getProjectRenders,
  getBatch,
  listCaptionPresets,
  renderCandidateOverride,
  renderCandidates,
  resolveMediaUrl,
  uploadProjectMusic,
} from '../api/client';
import type { BatchResponse, Candidate, CandidateEditorState, CaptionPreset, CompilationResponse, EditingSettings, ProjectFileItem, ProjectMusicAsset, ProjectSummary, RenderJob, ZoomInterval } from '../api/types';
import { AnalysisProgress } from '../components/AnalysisProgress';
import { BatchProgress } from '../components/BatchProgress';
import { CandidateEditorModal } from '../components/CandidateEditorModal';
import { CandidateGrid } from '../components/CandidateGrid';
import { PreviewModal } from '../components/PreviewModal';
import { RenderQueue } from '../components/RenderQueue';
import { Button, Card, EmptyState } from '../components/ui';
import { formatBytes, formatDate, formatDuration } from '../lib/format';

type TabKey = 'overview' | 'candidates' | 'tools' | 'renders' | 'files';

const tabs: Array<{ key: TabKey; label: string }> = [
  { key: 'overview', label: 'Overview' },
  { key: 'candidates', label: 'Candidates' },
  { key: 'tools', label: 'Create & Edit' },
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
  const [workspaceRetryable, setWorkspaceRetryable] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [busyAction, setBusyAction] = useState<'analyze' | 'refresh' | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>('overview');
  const [candidateScoreMin, setCandidateScoreMin] = useState('');
  const [candidateDurationMin, setCandidateDurationMin] = useState('');
  const [candidateRenderStatus, setCandidateRenderStatus] = useState('all');
  const [batch, setBatch] = useState<BatchResponse | null>(null);
  const [batchPollingError, setBatchPollingError] = useState<string | null>(null);
  const [batchTargetDuration, setBatchTargetDuration] = useState('30');
  const [batchSpacing, setBatchSpacing] = useState('5');
  const [batchMaxClips, setBatchMaxClips] = useState('');
  const [batchCaptions, setBatchCaptions] = useState(true);
  const [batchBusy, setBatchBusy] = useState(false);
  const [compilation, setCompilation] = useState<CompilationResponse | null>(null);
  const [compilationMaxDuration, setCompilationMaxDuration] = useState('90');
  const [compilationCaptions, setCompilationCaptions] = useState(true);
  const [compilationBusy, setCompilationBusy] = useState(false);
  const [compilationTrims, setCompilationTrims] = useState<Record<number, { start: number; end: number }>>({});
  const [captionPresets, setCaptionPresets] = useState<CaptionPreset[]>([]);
  const [editingCaptionPresetId, setEditingCaptionPresetId] = useState('');
  const [hookEnabled, setHookEnabled] = useState(false);
  const [hookText, setHookText] = useState('');
  const [hookPosition, setHookPosition] = useState<'top' | 'center' | 'bottom'>('center');
  const [zoomIntervals, setZoomIntervals] = useState<ZoomInterval[]>([]);
  const [musicAssets, setMusicAssets] = useState<ProjectMusicAsset[]>([]);
  const [musicAssetId, setMusicAssetId] = useState('');
  const [musicVolume, setMusicVolume] = useState('0.2');
  const [musicLoop, setMusicLoop] = useState(true);
  const [musicDuck, setMusicDuck] = useState(false);
  const [musicFadeIn, setMusicFadeIn] = useState('0');
  const [musicFadeOut, setMusicFadeOut] = useState('0');
  const [musicUploading, setMusicUploading] = useState(false);
  const [crossfadeEnabled, setCrossfadeEnabled] = useState(false);
  const [crossfadeDuration, setCrossfadeDuration] = useState('0.5');
  const batchRequestInFlight = useRef(false);
  const batchRefreshRef = useRef<() => void>(() => undefined);
  const workspaceLoadInFlight = useRef(false);
  const workspaceRetryCount = useRef(0);

  async function loadWorkspace(): Promise<boolean> {
    if (workspaceLoadInFlight.current) {
      return false;
    }
    workspaceLoadInFlight.current = true;
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
      setWorkspaceRetryable(false);
      workspaceRetryCount.current = 0;
      if (summary.status === 'completed' && summary.candidate_count > 0) {
        const candidateResponse = await getCandidates(videoId);
        setCandidates(candidateResponse.candidates);
        setSourceDuration(candidateResponse.source_duration ?? summary.source_duration ?? null);
      } else {
        setCandidates([]);
        setSourceDuration(summary.source_duration ?? null);
      }
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to load project workspace.');
      const retryable = cause instanceof Error
        && 'retryable' in cause
        && cause.retryable === true;
      setWorkspaceRetryable(retryable);
      return false;
    } finally {
      workspaceLoadInFlight.current = false;
    }
  }

  useEffect(() => {
    setProject(null);
    setCandidates([]);
    setSelectedIds([]);
    setBatch(null);
    setBatchPollingError(null);
    setCompilation(null);
    setWorkspaceRetryable(false);
    workspaceRetryCount.current = 0;
    let active = true;
    void loadWorkspace().then(() => {
      if (!active) {
        return;
      }
    });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId]);

  const projectIsActive = Boolean(project && ['queued', 'running'].includes(project.status));
  const retryAfterError = workspaceRetryable && !projectIsActive;

  useEffect(() => {
    const shouldPoll = projectIsActive || retryAfterError;
    if (!shouldPoll) {
      return undefined;
    }
    let active = true;
    let timeout: number | undefined;
    const poll = async () => {
      const succeeded = await loadWorkspace();
      if (!active) {
        return;
      }
      if (succeeded) {
        workspaceRetryCount.current = 0;
      } else {
        workspaceRetryCount.current += 1;
      }
      const delay = succeeded
        ? 3000
        : Math.min(3000 * (2 ** Math.max(0, workspaceRetryCount.current - 1)), 30000);
      timeout = window.setTimeout(() => void poll(), delay);
    };
    timeout = window.setTimeout(() => void poll(), 3000);
    return () => {
      active = false;
      if (timeout !== undefined) {
        window.clearTimeout(timeout);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId, project?.status, retryAfterError]);

  useEffect(() => {
    let active = true;
    Promise.all([listCaptionPresets(), getProjectMusic(videoId)]).then(([presets, assets]) => {
      if (active) {
        setCaptionPresets(presets);
        setMusicAssets(assets);
        if (musicAssetId && !assets.some((asset) => asset.asset_id === musicAssetId)) {
          setMusicAssetId('');
        }
      }
    }).catch((cause: unknown) => {
      if (active) {
        setError(cause instanceof Error ? cause.message : 'Unable to load smart-editing assets.');
      }
    });
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId]);

  useEffect(() => {
    if (!batch?.batch_id || !['queued', 'running'].includes(batch.status)) {
      batchRefreshRef.current = () => undefined;
      return undefined;
    }
    let active = true;
    const refresh = () => {
      if (batchRequestInFlight.current) {
        return;
      }
      batchRequestInFlight.current = true;
      void getBatch(batch.batch_id).then((next) => {
        if (active) {
          setBatch(next);
          setBatchPollingError(null);
        }
      }).catch((cause: unknown) => {
        if (active) {
          setBatchPollingError(cause instanceof Error ? cause.message : 'Unable to refresh batch status.');
        }
      }).finally(() => {
        batchRequestInFlight.current = false;
      });
    };
    batchRefreshRef.current = refresh;
    void refresh();
    const interval = window.setInterval(refresh, 2000);
    return () => {
      active = false;
      window.clearInterval(interval);
      if (batchRefreshRef.current === refresh) {
        batchRefreshRef.current = () => undefined;
      }
    };
  }, [batch?.batch_id, batch?.status, videoId]);

  useEffect(() => {
    if (!compilation?.compilation_id || !['queued', 'running'].includes(compilation.status)) {
      return undefined;
    }
    let active = true;
    const refresh = () => {
      void getCompilation(compilation.compilation_id).then((next) => {
        if (active) {
          setCompilation(next);
          if (next.status === 'completed') {
            void loadWorkspace();
          }
        }
      }).catch((cause: unknown) => {
        if (active) {
          setError(cause instanceof Error ? cause.message : 'Unable to refresh compilation status.');
        }
      });
    };
    const interval = window.setInterval(refresh, 2000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [compilation?.compilation_id, compilation?.status]);

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

  const compilationSegments = selectedIds.flatMap((candidateId) => {
    const candidate = candidates.find((item) => item.id === candidateId);
    if (!candidate) {
      return [];
    }
    const trim = compilationTrims[candidateId];
    return [{
      candidate,
      start: trim?.start ?? candidate.trim_start ?? candidate.start,
      end: trim?.end ?? candidate.trim_end ?? candidate.end,
    }];
  });
  const compilationEstimatedDuration = compilationSegments.reduce((total, segment) => total + segment.end - segment.start, 0);

  function toggleCandidate(candidateId: number) {
    setSelectedIds((current) => (current.includes(candidateId) ? current.filter((id) => id !== candidateId) : [...current, candidateId]));
  }

  function selectAll() {
    setSelectedIds(filteredCandidates.map((candidate) => candidate.id));
  }

  function clearSelection() {
    setSelectedIds([]);
  }

  function moveCompilationSegment(candidateId: number, offset: number) {
    setSelectedIds((current) => {
      const index = current.indexOf(candidateId);
      const destination = index + offset;
      if (index < 0 || destination < 0 || destination >= current.length) {
        return current;
      }
      const reordered = [...current];
      [reordered[index], reordered[destination]] = [reordered[destination], reordered[index]];
      return reordered;
    });
  }

  async function renderSelected() {
    if (!selectedIds.length) {
      return;
    }
    setRendering(true);
    setError(null);
    try {
      await renderCandidates(videoId, selectedIds, buildEditingSettings(false));
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
      await renderCandidateOverride(
        videoId,
        [candidate.id],
        { [String(candidate.id)]: { start, end } },
        { [String(candidate.id)]: state },
        buildEditingSettings(false),
      );
      setActiveTab('renders');
      await loadWorkspace();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to submit render job.');
    } finally {
      setRendering(false);
    }
  }

  async function startBatch() {
    const target = Number(batchTargetDuration);
    const spacing = Number(batchSpacing);
    const maxClips = batchMaxClips.trim() ? Number(batchMaxClips) : undefined;
    if (!Number.isFinite(target) || !Number.isFinite(spacing) || (maxClips !== undefined && !Number.isInteger(maxClips))) {
      setError('Enter valid batch duration, spacing, and clip count values.');
      return;
    }
    setBatchBusy(true);
    setError(null);
    const editing = buildEditingSettings(false);
    try {
      const response = await createBatch(videoId, {
        target_duration_seconds: target,
        minimum_spacing_seconds: spacing,
        ...(maxClips !== undefined ? { max_clips: maxClips } : {}),
        ...(selectedIds.length ? { candidate_ids: selectedIds } : {}),
        render_settings: { captions_enabled: batchCaptions },
        ...(editing ? { editing } : {}),
      });
      setBatch(response);
      setActiveTab('renders');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to start batch clips.');
    } finally {
      setBatchBusy(false);
    }
  }

  async function startCompilation() {
    const maxDuration = Number(compilationMaxDuration);
    if (!compilationSegments.length || !Number.isFinite(maxDuration) || maxDuration <= 0) {
      setError('Select at least one candidate and enter a valid maximum preferred duration.');
      return;
    }
    setCompilationBusy(true);
    setError(null);
    const editing = buildEditingSettings(true);
    try {
      const response = await createCompilation(videoId, {
        segments: compilationSegments.map(({ candidate, start, end }) => ({ candidate_id: candidate.id, start, end })),
        max_total_duration_seconds: maxDuration,
        render_settings: { captions_enabled: compilationCaptions },
        ...(editing ? { editing } : {}),
      });
      setCompilation(response);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to start compilation.');
    } finally {
      setCompilationBusy(false);
    }
  }

  function buildEditingSettings(includeTransition: boolean): EditingSettings | undefined {
    const settings: EditingSettings = {
      schema_version: 1,
      zoom_intervals: zoomIntervals,
      transition: includeTransition && crossfadeEnabled ? 'crossfade' : 'hard_cut',
      transition_duration_seconds: includeTransition && crossfadeEnabled ? Number(crossfadeDuration) : 0.5,
    };
    if (hookEnabled) {
      settings.hook = {
        text: hookText,
        start_seconds: 0,
        duration_seconds: 2.5,
        position: hookPosition,
        font_size: 64,
        color: '#FFFFFF',
        outline_width: 3,
        background_box: false,
        background_color: '#000000',
      };
    }
    if (musicAssetId) {
      settings.music = {
        asset_id: musicAssetId,
        volume: Number(musicVolume),
        loop: musicLoop,
        fade_in_seconds: Number(musicFadeIn),
        fade_out_seconds: Number(musicFadeOut),
        duck_original_audio: musicDuck,
      };
    }
    if (editingCaptionPresetId) {
      settings.caption_preset_id = editingCaptionPresetId;
    }
    const hasEffects = Boolean(settings.hook || settings.zoom_intervals.length || settings.music || settings.caption_preset_id);
    if (includeTransition && settings.transition === 'crossfade') {
      return settings;
    }
    return hasEffects ? settings : undefined;
  }

  async function handleMusicUpload(file: File | undefined) {
    if (!file) {
      return;
    }
    setMusicUploading(true);
    setError(null);
    try {
      const asset = await uploadProjectMusic(videoId, file);
      setMusicAssets((current) => [...current, asset]);
      setMusicAssetId(asset.asset_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to upload music.');
    } finally {
      setMusicUploading(false);
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
      await loadWorkspace();
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
    return (
      <Card className="p-6 text-sm text-slate-400" role={error ? 'alert' : undefined}>
        {error ?? 'Loading project workspace...'}
      </Card>
    );
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

      <nav aria-label="Project workspace sections" className="flex flex-wrap gap-2">
        {tabs.map((tab) => (
          <Button
            key={tab.key}
            type="button"
            variant={activeTab === tab.key ? 'primary' : 'secondary'}
            aria-pressed={activeTab === tab.key}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </Button>
        ))}
      </nav>

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

      {activeTab === 'candidates' || activeTab === 'tools' ? (
        <div className="space-y-4">
          {activeTab === 'candidates' ? (
            <>
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
            </>
          ) : null}
          {activeTab === 'tools' ? (
            <>
              <nav aria-label="Create and edit tools" className="flex flex-wrap gap-2 rounded-xl border border-surface-700 bg-surface-900 p-3">
                <a href="#batch-clips" className="rounded-lg px-3 py-2 text-sm text-slate-200 underline-offset-4 hover:bg-surface-800 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-400">Batch Clips</a>
                <a href="#auto-compilation" className="rounded-lg px-3 py-2 text-sm text-slate-200 underline-offset-4 hover:bg-surface-800 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-400">Auto-Compilation</a>
                <a href="#smart-editing" className="rounded-lg px-3 py-2 text-sm text-slate-200 underline-offset-4 hover:bg-surface-800 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-400">Smart Editing</a>
              </nav>
              {project.status !== 'completed' || candidates.length === 0 ? (
                <Card className="border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-100" role="status">
                  {project.status !== 'completed'
                    ? `Batch Clips and Auto-Compilation are unavailable until analysis completes (current status: ${project.status}).`
                    : project.candidate_count > 0
                      ? 'Analysis has candidates, but they are not available in this view yet. Check the workspace error above or refresh the project.'
                      : 'Analysis completed without candidates. Re-analyze the source or choose a project with detected moments to use Batch Clips and Auto-Compilation.'}
                </Card>
              ) : null}
            </>
          ) : null}
          {activeTab === 'tools' ? (
            <>
          <Card id="smart-editing" className="scroll-mt-6 space-y-4 p-4">
            <div>
              <h3 className="text-lg font-semibold text-white">Smart Editing</h3>
              <p className="mt-1 text-sm text-slate-400">Optional hook, bounded punch-ins, project-owned music, and a reusable caption style. These settings apply to individual renders and batch children; transitions apply only to compilations.</p>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="space-y-3 rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                <label className="flex items-center gap-2 text-sm text-slate-200">
                  <input checked={hookEnabled} onChange={(event) => setHookEnabled(event.target.checked)} type="checkbox" />
                  Opening hook overlay
                </label>
                {hookEnabled ? (
                  <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_9rem]">
                    <input value={hookText} onChange={(event) => setHookText(event.target.value)} maxLength={120} placeholder="Add a short opening hook" className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-white" />
                    <select value={hookPosition} onChange={(event) => setHookPosition(event.target.value as 'top' | 'center' | 'bottom')} className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-white">
                      <option value="top">Top</option><option value="center">Center</option><option value="bottom">Bottom</option>
                    </select>
                  </div>
                ) : null}
              </div>
              <div className="space-y-3 rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm text-slate-200">Punch-in zoom intervals</span>
                  <Button type="button" variant="secondary" onClick={() => setZoomIntervals((current) => {
                    const start = current.length ? Math.max(...current.map((item) => item.end_seconds)) + 0.5 : 1;
                    return start + 2 <= 600 ? [...current, { start_seconds: start, end_seconds: start + 2, scale: 1.15 }] : current;
                  })} disabled={zoomIntervals.length >= 12 || Math.max(1, ...zoomIntervals.map((item) => item.end_seconds + 0.5)) + 2 > 600}>Add interval</Button>
                </div>
                {zoomIntervals.map((interval, index) => (
                  <div key={`${index}-${interval.start_seconds}`} className="grid grid-cols-[1fr_1fr_1fr_auto] items-end gap-2">
                    <label className="text-xs text-slate-400">Start<input type="number" min="0" max="600" step="0.1" value={interval.start_seconds} onChange={(event) => setZoomIntervals((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, start_seconds: Number(event.target.value) } : item))} className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-900 px-2 py-1.5 text-sm text-white" /></label>
                    <label className="text-xs text-slate-400">End<input type="number" min="0.1" max="600" step="0.1" value={interval.end_seconds} onChange={(event) => setZoomIntervals((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, end_seconds: Number(event.target.value) } : item))} className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-900 px-2 py-1.5 text-sm text-white" /></label>
                    <label className="text-xs text-slate-400">Scale<input type="number" min="1.05" max="1.35" step="0.05" value={interval.scale} onChange={(event) => setZoomIntervals((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, scale: Number(event.target.value) } : item))} className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-900 px-2 py-1.5 text-sm text-white" /></label>
                    <Button type="button" variant="danger" onClick={() => setZoomIntervals((current) => current.filter((_, itemIndex) => itemIndex !== index))} aria-label={`Remove zoom interval ${index + 1}`}>×</Button>
                  </div>
                ))}
                {!zoomIntervals.length ? <p className="text-xs text-slate-500">No zoom intervals. Times are relative to each rendered clip or the final compilation.</p> : null}
              </div>
              <div className="space-y-3 rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                <div className="text-sm text-slate-200">Background music</div>
                <input type="file" accept=".mp3,.wav,.aac,.m4a,.ogg,.flac,audio/*" disabled={musicUploading} onChange={(event) => { void handleMusicUpload(event.target.files?.[0]); event.currentTarget.value = ''; }} className="block w-full text-sm text-slate-400 file:mr-3 file:rounded-lg file:border-0 file:bg-slate-800 file:px-3 file:py-2 file:text-slate-200" />
                <div className="grid gap-2 sm:grid-cols-2">
                  <select value={musicAssetId} onChange={(event) => setMusicAssetId(event.target.value)} className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-white"><option value="">Music disabled</option>{musicAssets.map((asset) => <option key={asset.asset_id} value={asset.asset_id}>{asset.filename} · {formatDuration(asset.duration_seconds)}</option>)}</select>
                  <label className="text-xs text-slate-400">Music volume<input type="number" min="0" max="1" step="0.05" value={musicVolume} onChange={(event) => setMusicVolume(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-white" /></label>
                  <label className="text-xs text-slate-400">Fade in (seconds)<input type="number" min="0" max="10" step="0.1" value={musicFadeIn} onChange={(event) => setMusicFadeIn(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-white" /></label>
                  <label className="text-xs text-slate-400">Fade out (seconds)<input type="number" min="0" max="10" step="0.1" value={musicFadeOut} onChange={(event) => setMusicFadeOut(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-white" /></label>
                </div>
                <div className="flex flex-wrap gap-4 text-sm text-slate-300">
                  <label className="flex items-center gap-2"><input checked={musicLoop} onChange={(event) => setMusicLoop(event.target.checked)} type="checkbox" />Loop to output length</label>
                  <label className="flex items-center gap-2"><input checked={musicDuck} onChange={(event) => setMusicDuck(event.target.checked)} type="checkbox" />Duck music under original audio</label>
                </div>
                <p className="text-xs text-slate-500">Ducking responds to overall source audio activity, not speech recognition.</p>
              </div>
              <div className="space-y-3 rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                <label className="block space-y-1 text-sm text-slate-300">
                  <span>Caption preset</span>
                  <select value={editingCaptionPresetId} onChange={(event) => setEditingCaptionPresetId(event.target.value)} className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-white">
                    <option value="">Keep existing caption settings</option>
                    {captionPresets.map((preset) => <option key={preset.id} value={preset.id}>{preset.name}{preset.built_in ? ' (built-in)' : ''}</option>)}
                  </select>
                </label>
                <label className="flex items-center gap-2 text-sm text-slate-300">
                  <input checked={crossfadeEnabled} onChange={(event) => setCrossfadeEnabled(event.target.checked)} type="checkbox" />
                  Crossfade between compilation segments
                </label>
                {crossfadeEnabled ? <label className="block space-y-1 text-xs text-slate-400">Overlap duration (seconds)<input type="number" min="0.1" max="2" step="0.1" value={crossfadeDuration} onChange={(event) => setCrossfadeDuration(event.target.value)} className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-white" /></label> : null}
                <p className="text-xs text-slate-500">Crossfade shortens the final output by the overlap at each boundary. Individual clips and batch children remain hard-cut outputs.</p>
              </div>
            </div>
          </Card>
          <Card id="auto-compilation" className="scroll-mt-6 space-y-4 p-4">
            <div>
              <h3 className="text-lg font-semibold text-white">Auto-Compilation</h3>
              <p className="mt-1 text-sm text-slate-400">Compiles selected moments as hard cuts in the order shown. If the preferred maximum is exceeded, only the final moment is shortened, and only when it remains renderable.</p>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <label className="space-y-1 text-sm text-slate-300">
                <span className="text-xs uppercase tracking-[0.22em] text-slate-500">Maximum preferred duration (seconds)</span>
                <input value={compilationMaxDuration} onChange={(event) => setCompilationMaxDuration(event.target.value)} type="number" min="1" max="600" step="0.5" className="w-full rounded-xl border border-slate-800 bg-slate-950/80 px-3 py-2 text-sm text-white" />
              </label>
              <label className="flex items-end gap-2 pb-2 text-sm text-slate-300">
                <input checked={compilationCaptions} onChange={(event) => setCompilationCaptions(event.target.checked)} type="checkbox" />
                Burn in captions
              </label>
              <div className="flex items-end pb-2 text-sm text-slate-300">
                Estimated output: {formatDuration(Math.min(compilationEstimatedDuration, Number(compilationMaxDuration) || 0))}
                {compilationEstimatedDuration > (Number(compilationMaxDuration) || 0) ? ' (final segment may be trimmed)' : ''}
              </div>
            </div>
            {compilationSegments.length ? (
              <ol className="space-y-2">
                {compilationSegments.map(({ candidate, start, end }, index) => (
                  <li key={candidate.id} className="grid gap-3 rounded-xl border border-slate-800 bg-slate-950/60 p-3 md:grid-cols-[minmax(0,1fr)_8rem_8rem_auto] md:items-end">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold text-white">{index + 1}. Candidate #{candidate.id}</div>
                      <div className="mt-1 line-clamp-2 text-xs text-slate-400">{candidate.transcript || 'Transcript unavailable'}</div>
                      <div className="mt-1 text-xs text-slate-500">{formatDuration(end - start)}</div>
                    </div>
                    <label className="space-y-1 text-xs text-slate-400">
                      <span>Start (seconds)</span>
                      <input value={start} onChange={(event) => setCompilationTrims((current) => ({ ...current, [candidate.id]: { start: Number(event.target.value), end } }))} type="number" min={candidate.start} max={candidate.end} step="0.1" className="w-full rounded-lg border border-slate-800 bg-slate-950 px-2 py-1.5 text-sm text-white" />
                    </label>
                    <label className="space-y-1 text-xs text-slate-400">
                      <span>End (seconds)</span>
                      <input value={end} onChange={(event) => setCompilationTrims((current) => ({ ...current, [candidate.id]: { start, end: Number(event.target.value) } }))} type="number" min={candidate.start} max={candidate.end} step="0.1" className="w-full rounded-lg border border-slate-800 bg-slate-950 px-2 py-1.5 text-sm text-white" />
                    </label>
                    <div className="flex gap-1">
                      <Button type="button" variant="secondary" onClick={() => moveCompilationSegment(candidate.id, -1)} disabled={index === 0} aria-label={`Move candidate ${candidate.id} up`}>↑</Button>
                      <Button type="button" variant="secondary" onClick={() => moveCompilationSegment(candidate.id, 1)} disabled={index === compilationSegments.length - 1} aria-label={`Move candidate ${candidate.id} down`}>↓</Button>
                      <Button type="button" variant="danger" onClick={() => toggleCandidate(candidate.id)} aria-label={`Remove candidate ${candidate.id}`}>×</Button>
                    </div>
                  </li>
                ))}
              </ol>
            ) : <p className="text-sm text-slate-500">Select moments below to build an ordered compilation.</p>}
            <div className="flex flex-wrap items-center gap-3">
              <Button type="button" onClick={() => void startCompilation()} disabled={compilationBusy || project.status !== 'completed' || !candidates.length || !compilationSegments.length || compilationSegments.length > 50}>
                {compilationBusy ? 'Starting...' : 'Create compilation'}
              </Button>
              {compilationSegments.length > 50 ? <span className="text-xs text-amber-300">Select at most 50 moments.</span> : null}
              {compilation ? <span className="text-sm text-slate-300">{compilation.status} · {Math.round(compilation.progress)}% · {formatDuration(compilation.effective_duration_seconds)}</span> : null}
            </div>
            {compilation?.message ? <p className="text-sm text-slate-400">{compilation.message}</p> : null}
            {compilation?.failure ? <p className="text-sm text-rose-300">{compilation.failure}</p> : null}
            {compilation?.status === 'completed' && compilation.output_url ? (
              <div className="space-y-3">
                <video src={resolveMediaUrl(compilation.output_url) ?? compilation.output_url} controls preload="metadata" className="max-h-96 w-full rounded-xl bg-black" />
                <a href={resolveMediaUrl(compilation.output_url) ?? compilation.output_url} target="_blank" rel="noreferrer" className="inline-flex text-sm text-sky-300 underline underline-offset-4">Open completed compilation</a>
              </div>
            ) : null}
          </Card>
          <Card id="batch-clips" className="scroll-mt-6 space-y-4 p-4">
            <div>
              <h3 className="text-lg font-semibold text-white">Batch Clips</h3>
              <p className="mt-1 text-sm text-slate-400">Selects the highest-scoring distinct moments, trims each to at most the target duration, and renders independent vertical clips.</p>
            </div>
            <div className="grid gap-3 md:grid-cols-4">
              <label className="space-y-1 text-sm text-slate-300"><span className="text-xs uppercase tracking-[0.22em] text-slate-500">Target max seconds</span><input value={batchTargetDuration} onChange={(event) => setBatchTargetDuration(event.target.value)} type="number" min="1" step="0.5" className="w-full rounded-xl border border-slate-800 bg-slate-950/80 px-3 py-2 text-sm text-white" /></label>
              <label className="space-y-1 text-sm text-slate-300"><span className="text-xs uppercase tracking-[0.22em] text-slate-500">Minimum spacing</span><input value={batchSpacing} onChange={(event) => setBatchSpacing(event.target.value)} type="number" min="0" step="0.5" className="w-full rounded-xl border border-slate-800 bg-slate-950/80 px-3 py-2 text-sm text-white" /></label>
              <label className="space-y-1 text-sm text-slate-300"><span className="text-xs uppercase tracking-[0.22em] text-slate-500">Max clips</span><input value={batchMaxClips} onChange={(event) => setBatchMaxClips(event.target.value)} type="number" min="1" step="1" placeholder="Default" className="w-full rounded-xl border border-slate-800 bg-slate-950/80 px-3 py-2 text-sm text-white" /></label>
              <label className="flex items-end gap-2 pb-2 text-sm text-slate-300"><input checked={batchCaptions} onChange={(event) => setBatchCaptions(event.target.checked)} type="checkbox" /> Captions</label>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button type="button" onClick={() => void startBatch()} disabled={batchBusy || rendering || project.status !== 'completed' || !candidates.length}>{batchBusy ? 'Starting...' : `Generate batch${selectedIds.length ? ` (${selectedIds.length} selected)` : ''}`}</Button>
            </div>
            {batch ? (
              <BatchProgress
                batch={batch}
                pollingError={batchPollingError}
                onRetryPolling={['queued', 'running'].includes(batch.status) ? () => batchRefreshRef.current() : undefined}
              />
            ) : null}
          </Card>
            </>
          ) : null}
          {activeTab === 'candidates' ? (
            candidates.length ? (
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
            )
          ) : null}
        </div>
      ) : null}

      {activeTab === 'renders' ? (
        <div className="space-y-4">
          {batch ? (
            <BatchProgress
              batch={batch}
              pollingError={batchPollingError}
              onRetryPolling={['queued', 'running'].includes(batch.status) ? () => batchRefreshRef.current() : undefined}
            />
          ) : null}
          <RenderQueue
            jobs={renderJobs.filter((job) => job.video_id === project.video_id)}
            onNeedsChanges={(job) => {
              const candidate = candidates.find((item) => item.id === job.candidate_id);
              if (candidate) {
                setActiveTab('candidates');
                setEditingCandidate(candidate);
              }
            }}
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