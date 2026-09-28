import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { analyzeVideo, listProjects } from '../api/client';
import type { ProjectSummary } from '../api/types';
import { formatDate, formatDuration } from '../lib/format';
import { Badge, Button, Card, EmptyState } from '../components/ui';
import { UrlInput } from '../components/UrlInput';

export function AnalyzePage() {
	const navigate = useNavigate();
	const [url, setUrl] = useState('');
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [projects, setProjects] = useState<ProjectSummary[]>([]);

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
					setError(cause instanceof Error ? cause.message : 'Unable to load recent workspaces.');
				}
			});
		return () => {
			active = false;
		};
	}, []);

	const recentProjects = useMemo(() => [...projects].sort((left, right) => (right.latest_activity_at ?? right.updated_at ?? '').localeCompare(left.latest_activity_at ?? left.updated_at ?? '')).slice(0, 6), [projects]);

	async function handleAnalyze() {
		if (!url.trim()) {
			setError('Paste a supported video URL first.');
			return;
		}
		setLoading(true);
		setError(null);
		try {
			const response = await analyzeVideo(url.trim());
			navigate(`/projects/${response.video_id}`);
		} catch (cause) {
			setError(cause instanceof Error ? cause.message : 'Unable to start analysis.');
		} finally {
			setLoading(false);
		}
	}

	return (
		<div className="space-y-6">
			<section className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
				<Card className="p-6 sm:p-8">
					<div className="max-w-2xl space-y-5">
						<div className="inline-flex items-center gap-2 rounded-full border border-accent-500/20 bg-accent-500/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.18em] text-accent-300">
							Analysis workflow
						</div>
						<div>
							<h2 className="text-3xl font-semibold tracking-tight text-white sm:text-[2.25rem]">Start a new local analysis.</h2>
							<p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">Paste a YouTube URL, launch detection, then continue in the project workspace where candidates, trims, captions, and renders are managed.</p>
						</div>
						<div className="space-y-3">
							<UrlInput value={url} onChange={setUrl} onSubmit={handleAnalyze} loading={loading} />
							{error ? <p className="text-sm text-danger-100">{error}</p> : <p className="text-sm text-slate-400">Analysis runs locally and opens the resulting project workspace when it completes.</p>}
						</div>
					</div>
				</Card>

				<Card className="p-6">
					<div className="space-y-4">
						<div>
							<div className="text-xs uppercase tracking-[0.2em] text-slate-500">Workflow</div>
							<h3 className="mt-2 text-lg font-semibold text-white">What happens next</h3>
						</div>
						<div className="space-y-3 text-sm text-slate-300">
							<div className="rounded-xl border border-surface-700 bg-surface-800 px-4 py-3">1. The backend downloads or reuses the source video cache.</div>
							<div className="rounded-xl border border-surface-700 bg-surface-800 px-4 py-3">2. Candidates are detected from transcript, audio, and scene signals.</div>
							<div className="rounded-xl border border-surface-700 bg-surface-800 px-4 py-3">3. You review the workspace and choose clips to trim or render.</div>
						</div>
					</div>
				</Card>
			</section>

			<section className="space-y-4">
				<div>
					<div className="text-xs uppercase tracking-[0.2em] text-slate-500">Recent workspaces</div>
					<h3 className="mt-2 text-xl font-semibold text-white">Open a project or continue an analysis</h3>
				</div>

				{recentProjects.length ? (
					<div className="grid gap-4 lg:grid-cols-2">
						{recentProjects.map((project) => (
							<button key={project.video_id} type="button" onClick={() => navigate(`/projects/${project.video_id}`)} className="group rounded-2xl border border-surface-700 bg-surface-900 p-5 text-left shadow-subtle transition hover:border-accent-500/30 hover:bg-surface-800">
								<div className="flex items-start justify-between gap-4">
									<div className="min-w-0">
										<div className="truncate text-base font-medium text-white">{project.title ?? project.video_id}</div>
										<div className="mt-1 text-xs text-slate-500">{project.video_id}</div>
									</div>
									<Badge variant={project.status === 'completed' ? 'completed' : project.status === 'failed' || project.status === 'interrupted' ? 'failed' : project.status === 'running' ? 'running' : 'queued'}>{project.status}</Badge>
								</div>
								<div className="mt-4 grid gap-2 text-sm text-slate-400 sm:grid-cols-2">
									<div>{project.candidate_count} candidates</div>
									<div>{project.rendered_count} renders</div>
									<div>{project.source_duration != null ? formatDuration(project.source_duration) : 'Unknown duration'}</div>
									<div>{project.latest_activity_at ? formatDate(project.latest_activity_at) : 'No recent activity'}</div>
								</div>
							</button>
						))}
					</div>
				) : (
					<EmptyState title="No recent projects" description="Analyze a video to create the first project workspace." action={<Button type="button" onClick={handleAnalyze} disabled={loading}>Analyze video</Button>} />
				)}
			</section>
		</div>
	);
}