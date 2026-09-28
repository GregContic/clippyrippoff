import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { analyzeVideo, listVideos } from '../api/client';
import type { ProjectSummary } from '../api/types';
import { formatDate } from '../lib/format';
import { Button, Card, EmptyState } from '../components/ui';
import { UrlInput } from '../components/UrlInput';

export function DashboardPage() {
  const navigate = useNavigate();
  const [url, setUrl] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    listVideos()
      .then((response) => {
        if (active) {
          setProjects(response.items);
        }
      })
      .catch((err: unknown) => {
        if (active) {
          setError(err instanceof Error ? err.message : 'Unable to load recent videos.');
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
      navigate(`/analyze/${response.video_id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to analyze this video.');
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="space-y-8">
      <section className="grid gap-6 xl:grid-cols-[1.35fr_0.9fr]">
        <Card className="overflow-hidden p-6 sm:p-8">
          <div className="max-w-2xl space-y-5">
            <div className="inline-flex items-center gap-2 rounded-full border border-sky-400/20 bg-sky-400/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.22em] text-sky-200">
              Local desktop workflow
            </div>
            <div>
              <h2 className="text-3xl font-semibold tracking-tight text-white sm:text-5xl">Turn long videos into Shorts.</h2>
              <p className="mt-4 max-w-xl text-base leading-7 text-slate-400">Paste a YouTube URL and let ClippyRipoff find the moments worth clipping.</p>
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
              <div className="mt-2 text-lg font-semibold text-white">Everything stays on your machine.</div>
              <p className="mt-2 text-sm leading-6 text-slate-400">The backend wraps the existing Python engine through HTTP and keeps the cache in the project workspace.</p>
            </div>
            <div className="grid gap-3 text-sm text-slate-300">
              <div className="rounded-xl border border-slate-800 bg-slate-950/50 px-4 py-3">Analyze YouTube URLs</div>
              <div className="rounded-xl border border-slate-800 bg-slate-950/50 px-4 py-3">Review ranked candidates</div>
              <div className="rounded-xl border border-slate-800 bg-slate-950/50 px-4 py-3">Render selected Shorts</div>
            </div>
          </div>
        </Card>
      </section>

      <section className="space-y-4">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h3 className="text-xl font-semibold text-white">Recent Videos</h3>
            <p className="mt-1 text-sm text-slate-400">Projects cached locally by the analysis pipeline.</p>
          </div>
          <Button type="button" variant="ghost" onClick={() => listVideos().then((response) => setProjects(response.items)).catch(() => undefined)}>
            Refresh
          </Button>
        </div>

        {projects.length ? (
          <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
            {projects.map((project) => (
              <Card key={project.video_id} className="p-5">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="text-sm font-semibold text-white">{project.title ?? project.video_id}</div>
                    <div className="mt-2 text-sm text-slate-400">{project.candidate_count} candidates • {project.rendered_count} rendered</div>
                    <div className="mt-1 text-xs text-slate-500">Updated {formatDate(project.updated_at)}</div>
                  </div>
                  <div className="rounded-full border border-slate-800 bg-slate-950/60 px-3 py-1 text-xs uppercase tracking-[0.2em] text-slate-400">{project.status}</div>
                </div>

                <div className="mt-5 flex gap-2">
                  <Button type="button" variant="secondary" onClick={() => navigate(`/analyze/${project.video_id}`)} className="flex-1">
                    Open Project
                  </Button>
                  {project.rendered_urls[0] ? (
                    <a href={project.rendered_urls[0]} target="_blank" rel="noreferrer" className="inline-flex flex-1 items-center justify-center rounded-xl border border-slate-700 bg-slate-800/80 px-4 py-2 text-sm font-semibold text-slate-100 transition hover:border-sky-400/40 hover:bg-slate-700/80">
                      Play
                    </a>
                  ) : null}
                </div>
              </Card>
            ))}
          </div>
        ) : (
          <EmptyState title="No videos analyzed yet." description="Paste a YouTube URL above to create your first local project." />
        )}
      </section>
    </div>
  );
}
