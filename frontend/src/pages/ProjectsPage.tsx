import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { analyzeVideo, listProjects, resolveMediaUrl } from '../api/client';
import type { ProjectSummary } from '../api/types';
import { formatDate, formatDuration } from '../lib/format';
import { Button, Card, EmptyState } from '../components/ui';
import { UrlInput } from '../components/UrlInput';

type SortKey = 'recently-updated' | 'recently-analyzed' | 'title';
type StatusFilter = 'all' | 'analyzed' | 'processing' | 'has-renders' | 'failed';

export function ProjectsPage() {
  const navigate = useNavigate();
  const [url, setUrl] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [sortBy, setSortBy] = useState<SortKey>('recently-updated');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');

  useEffect(() => {
    let active = true;
    listProjects()
      .then((response) => {
        if (active) {
          setProjects(response.items);
        }
      })
      .catch((cause: unknown) => {
        if (active) {
          setError(cause instanceof Error ? cause.message : 'Unable to load projects.');
        }
      });
    return () => {
      active = false;
    };
  }, []);

  async function handleAnalyze() {
    if (!url.trim()) {
      setError('Paste a YouTube URL first.');
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      const response = await analyzeVideo(url.trim());
      navigate(`/projects/${response.video_id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to analyze this video.');
    } finally {
      setIsSubmitting(false);
    }
  }

  const visibleProjects = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return [...projects]
      .filter((project) => {
        const matchesQuery = !normalized || `${project.title ?? ''} ${project.video_id}`.toLowerCase().includes(normalized);
        const matchesStatus =
          statusFilter === 'all' ||
          (statusFilter === 'analyzed' && project.status === 'completed') ||
          (statusFilter === 'processing' && ['queued', 'running'].includes(project.status)) ||
          (statusFilter === 'has-renders' && (project.rendered_count ?? 0) > 0) ||
          (statusFilter === 'failed' && ['failed', 'interrupted'].includes(project.status));
        return matchesQuery && matchesStatus;
      })
      .sort((left, right) => {
        if (sortBy === 'title') {
          return (left.title ?? left.video_id).localeCompare(right.title ?? right.video_id);
        }
        if (sortBy === 'recently-analyzed') {
          return (right.last_analyzed_at ?? right.updated_at ?? '').localeCompare(left.last_analyzed_at ?? left.updated_at ?? '');
        }
        return (right.latest_activity_at ?? right.updated_at ?? '').localeCompare(left.latest_activity_at ?? left.updated_at ?? '');
      });
  }, [projects, query, sortBy, statusFilter]);

  return (
    <div className="space-y-8">
      <section className="grid gap-6 xl:grid-cols-[1.35fr_0.9fr]">
        <Card className="overflow-hidden p-6 sm:p-8">
          <div className="max-w-2xl space-y-5">
            <div className="inline-flex items-center gap-2 rounded-full border border-sky-400/20 bg-sky-400/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.22em] text-sky-200">
              Local project workspace
            </div>
            <div>
              <h2 className="text-3xl font-semibold tracking-tight text-white sm:text-5xl">Turn long videos into managed projects.</h2>
              <p className="mt-4 max-w-xl text-base leading-7 text-slate-400">Paste a YouTube URL, analyze a clip, and manage candidates, render jobs, and generated files from the project workspace.</p>
            </div>
            <div className="space-y-3">
              <UrlInput value={url} onChange={setUrl} onSubmit={handleAnalyze} loading={isSubmitting} />
              {error ? <p className="text-sm text-rose-300">{error}</p> : null}
            </div>
          </div>
        </Card>

        <Card className="p-6">
          <div className="space-y-4">
            <div>
              <div className="text-sm uppercase tracking-[0.24em] text-slate-500">Local only</div>
              <div className="mt-2 text-lg font-semibold text-white">Projects stay on this machine.</div>
              <p className="mt-2 text-sm leading-6 text-slate-400">The workspace reuses the existing project cache, editor state, and render history saved under the repo.</p>
            </div>
            <div className="grid gap-3 text-sm text-slate-300">
              <div className="rounded-xl border border-slate-800 bg-slate-950/50 px-4 py-3">Analyze and revisit projects</div>
              <div className="rounded-xl border border-slate-800 bg-slate-950/50 px-4 py-3">Manage candidate trims and captions</div>
              <div className="rounded-xl border border-slate-800 bg-slate-950/50 px-4 py-3">Inspect renders and generated clips</div>
            </div>
          </div>
        </Card>
      </section>

      <section className="space-y-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h3 className="text-xl font-semibold text-white">Projects</h3>
            <p className="mt-1 text-sm text-slate-400">Each analyzed video keeps its own filesystem-backed workspace.</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="space-y-1 text-sm text-slate-300">
              <span className="text-xs uppercase tracking-[0.22em] text-slate-500">Search</span>
              <input value={query} onChange={(event) => setQuery(event.target.value)} className="w-full rounded-xl border border-slate-800 bg-slate-950/80 px-3 py-2 text-sm text-white" placeholder="Title or video ID" />
            </label>
            <label className="space-y-1 text-sm text-slate-300">
              <span className="text-xs uppercase tracking-[0.22em] text-slate-500">Sort</span>
              <select value={sortBy} onChange={(event) => setSortBy(event.target.value as SortKey)} className="w-full rounded-xl border border-slate-800 bg-slate-950/80 px-3 py-2 text-sm text-white">
                <option value="recently-updated">Recently updated</option>
                <option value="recently-analyzed">Recently analyzed</option>
                <option value="title">Title</option>
              </select>
            </label>
            <label className="space-y-1 text-sm text-slate-300">
              <span className="text-xs uppercase tracking-[0.22em] text-slate-500">Filter</span>
              <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as StatusFilter)} className="w-full rounded-xl border border-slate-800 bg-slate-950/80 px-3 py-2 text-sm text-white">
                <option value="all">All projects</option>
                <option value="analyzed">Analyzed</option>
                <option value="processing">Processing</option>
                <option value="has-renders">Has rendered clips</option>
                <option value="failed">Failed or interrupted</option>
              </select>
            </label>
          </div>
        </div>

        {visibleProjects.length ? (
          <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
            {visibleProjects.map((project) => (
              <Card key={project.video_id} className="overflow-hidden p-0">
                <div className="bg-slate-950/80">
                  {project.source_thumbnail_url ? (
                    <img src={resolveMediaUrl(project.source_thumbnail_url) ?? project.source_thumbnail_url} alt={project.title ?? project.video_id} className="h-44 w-full object-cover" />
                  ) : (
                    <div className="flex h-44 items-center justify-center bg-surface-800 text-sm uppercase tracking-[0.24em] text-slate-500">{project.video_id}</div>
                  )}
                </div>
                <div className="space-y-4 p-5">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <div className="text-base font-semibold text-white">{project.title ?? project.video_id}</div>
                      <div className="mt-1 text-xs text-slate-500">{project.video_id}</div>
                      <div className="mt-2 text-sm text-slate-400">{project.candidate_count} candidates • {project.rendered_count} rendered • {project.source_duration != null ? formatDuration(project.source_duration) : 'unknown source length'}</div>
                    </div>
                    <div className="rounded-full border border-slate-800 bg-slate-950/60 px-3 py-1 text-xs uppercase tracking-[0.2em] text-slate-400">{project.status}</div>
                  </div>

                  <div className="grid gap-2 text-xs text-slate-400 sm:grid-cols-2">
                    <div>Latest activity: {project.latest_activity_at ? formatDate(project.latest_activity_at) : 'unknown'}</div>
                    <div>Source cache: {project.source_cache_status ?? 'unknown'}</div>
                    <div>Saved trims: {project.manual_trim_count ?? 0}</div>
                    <div>Queued jobs: {project.queued_render_jobs ?? 0}</div>
                  </div>

                  <div className="flex gap-2">
                    <Button type="button" variant="secondary" onClick={() => navigate(`/projects/${project.video_id}`)} className="flex-1">
                      Open project
                    </Button>
                    {project.rendered_urls[0] ? (
                      <a href={resolveMediaUrl(project.rendered_urls[0]) ?? project.rendered_urls[0]} target="_blank" rel="noreferrer" className="inline-flex flex-1 items-center justify-center rounded-xl border border-slate-700 bg-slate-800/80 px-4 py-2 text-sm font-semibold text-slate-100 transition hover:border-sky-400/40 hover:bg-slate-700/80">
                        Play
                      </a>
                    ) : null}
                  </div>
                </div>
              </Card>
            ))}
          </div>
        ) : (
          <EmptyState title="No projects match your filters" description="Paste a YouTube URL above to create a new local project." />
        )}
      </section>
    </div>
  );
}