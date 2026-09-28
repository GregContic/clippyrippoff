import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getCandidates, getVideo, renderCandidates } from '../api/client';
import type { Candidate, ProjectSummary } from '../api/types';
import { AnalysisProgress } from '../components/AnalysisProgress';
import { CandidateGrid } from '../components/CandidateGrid';
import { PreviewModal } from '../components/PreviewModal';
import { Button, Card, EmptyState } from '../components/ui';

export function AnalyzePage() {
  const { videoId = '' } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [activeCandidate, setActiveCandidate] = useState<Candidate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rendering, setRendering] = useState(false);

  const shouldPoll = project?.status !== 'completed' && project?.status !== 'failed';

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const summary = await getVideo(videoId);
        if (!active) {
          return;
        }
        setProject(summary);
        setError(null);
        if (summary.status === 'completed' && summary.candidate_count > 0) {
          const candidateResponse = await getCandidates(videoId);
          if (active) {
            setCandidates(candidateResponse.candidates);
          }
        } else if (summary.status === 'failed') {
          setCandidates([]);
        }
      } catch (cause) {
        if (active) {
          setError(cause instanceof Error ? cause.message : 'Unable to load project state.');
        }
      }
    }

    void load();
    const interval = window.setInterval(() => {
      if (shouldPoll) {
        void load();
      }
    }, shouldPoll ? 3000 : 6000);

    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [shouldPoll, videoId]);

  useEffect(() => {
    if (project?.status === 'completed' && project.candidate_count > 0 && !candidates.length) {
      void getCandidates(videoId)
        .then((response) => setCandidates(response.candidates))
        .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : 'Unable to load candidates.'));
    }
  }, [candidates.length, project?.candidate_count, project?.status, videoId]);

  const candidateIds = useMemo(() => candidates.map((candidate) => candidate.id), [candidates]);

  function toggleCandidate(candidateId: number) {
    setSelectedIds((current) =>
      current.includes(candidateId) ? current.filter((id) => id !== candidateId) : [...current, candidateId],
    );
  }

  function selectAll() {
    setSelectedIds(candidateIds);
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
      navigate('/renders');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to submit render jobs.');
    } finally {
      setRendering(false);
    }
  }

  const previewUrl = activeCandidate?.preview_url ?? project?.source_video_url ?? null;

  return (
    <div className="space-y-6">
      {project ? (
        <Card className="p-5">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <div className="text-xs uppercase tracking-[0.24em] text-slate-500">Project</div>
              <h2 className="mt-2 text-2xl font-semibold text-white">{project.title ?? project.video_id}</h2>
              <p className="mt-2 text-sm text-slate-400">{project.candidate_count} candidates • {project.rendered_count} rendered</p>
            </div>
            <div className="text-sm text-slate-400">
              <div>Status: <span className="text-white">{project.status}</span></div>
              <div>Stage: <span className="text-white">{project.analysis_stage ?? '—'}</span></div>
            </div>
          </div>
        </Card>
      ) : null}

      {project?.status !== 'completed' ? (
        <AnalysisProgress stage={project?.analysis_stage} message={project?.message} status={project?.status ?? 'loading'} />
      ) : null}

      {error ? <Card className="border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-100">{error}</Card> : null}

      {project?.status === 'failed' ? (
        <EmptyState title="Unable to analyze this video." description={project.message ?? 'The analysis job failed on the backend.'} action={<Button type="button" variant="secondary" onClick={() => navigate('/')}>Back to dashboard</Button>} />
      ) : null}

      {project?.status === 'completed' ? (
        <CandidateGrid
          candidates={candidates}
          selectedIds={selectedIds}
          onToggle={toggleCandidate}
          onSelectAll={selectAll}
          onClear={clearSelection}
          onPreview={(candidate) => setActiveCandidate(candidate)}
          onRender={renderSelected}
          busy={rendering}
        />
      ) : null}

      <PreviewModal candidate={activeCandidate} previewUrl={previewUrl} onClose={() => setActiveCandidate(null)} />
    </div>
  );
}
