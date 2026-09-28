import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { listProjects, listRenders, resolveMediaUrl } from '../api/client';
import type { ProjectSummary, RenderJob } from '../api/types';
import { formatDate, formatDuration } from '../lib/format';
import { Badge, Button, Card, EmptyState, StatCard } from '../components/ui';

export function DashboardPage() {
	const navigate = useNavigate();
	const [projects, setProjects] = useState<ProjectSummary[]>([]);
	const [renders, setRenders] = useState<RenderJob[]>([]);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		let active = true;
		Promise.all([listProjects(), listRenders()])
			.then(([projectResponse, renderResponse]) => {
				if (!active) {
					return;
				}
				setProjects(projectResponse.items);
				setRenders(renderResponse);
			})
			.catch((cause: unknown) => {
				if (active) {
					setError(cause instanceof Error ? cause.message : 'Unable to load dashboard.');
				}
			});
		return () => {
			active = false;
		};
	}, []);

	const analyzedCount = projects.filter((project) => project.status === 'completed').length;
	const candidateCount = projects.reduce((total, project) => total + (project.candidate_count ?? 0), 0);
	const renderCount = renders.length;
	const completedRenders = renders.filter((job) => job.status === 'completed').length;
	const recentProjects = [...projects].sort((left, right) => (right.latest_activity_at ?? right.updated_at ?? '').localeCompare(left.latest_activity_at ?? left.updated_at ?? '')).slice(0, 4);
	const recentRenders = [...renders].sort((left, right) => right.updated_at.localeCompare(left.updated_at)).slice(0, 5);

	return (
		<div className="space-y-6">
			{error ? <Card className="border-danger-500/30 bg-danger-500/10 p-4 text-sm text-danger-100">{error}</Card> : null}

			<section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
				<StatCard label="Analyzed projects" value={analyzedCount} detail="Projects with completed candidate detection." />
				<StatCard label="Clip candidates" value={candidateCount} detail="Total candidates across local project workspaces." />
				<StatCard label="Render jobs" value={renderCount} detail="Queued, running, failed, and completed local jobs." />
				<StatCard label="Completed renders" value={completedRenders} detail="Finished Shorts available in the library." />
			</section>

			<section className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
				<Card className="p-6">
					<div className="flex items-start justify-between gap-4">
						<div>
							<div className="text-xs uppercase tracking-[0.2em] text-slate-500">Workspace overview</div>
							<h2 className="mt-2 text-xl font-semibold text-white">Recent projects</h2>
							<p className="mt-1 text-sm text-slate-400">Open a project workspace to review candidates, trim clips, or submit renders.</p>
						</div>
						<Button type="button" variant="secondary" onClick={() => navigate('/analyze')}>Start analysis</Button>
					</div>

					<div className="mt-5 space-y-3">
						{recentProjects.length ? recentProjects.map((project) => (
							<button key={project.video_id} type="button" onClick={() => navigate(`/projects/${project.video_id}`)} className="flex w-full items-center justify-between gap-4 rounded-xl border border-surface-700 bg-surface-800 px-4 py-3 text-left transition hover:border-accent-500/30 hover:bg-surface-700">
								<div className="min-w-0">
									<div className="truncate font-medium text-white">{project.title ?? project.video_id}</div>
									<div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
										<span>{project.video_id}</span>
										<span>•</span>
										<span>{project.candidate_count} candidates</span>
										<span>•</span>
										<span>{project.rendered_count} renders</span>
										<span>•</span>
										<span>{project.source_duration != null ? formatDuration(project.source_duration) : 'Unknown duration'}</span>
									</div>
								</div>
								<Badge variant={project.status === 'completed' ? 'completed' : project.status === 'failed' || project.status === 'interrupted' ? 'failed' : project.status === 'running' ? 'running' : 'queued'}>{project.status}</Badge>
							</button>
						)) : <EmptyState title="No projects yet" description="Start an analysis to create the first local workspace." action={<Button type="button" onClick={() => navigate('/analyze')}>Analyze video</Button>} />}
					</div>
				</Card>

				<Card className="p-6">
					<div>
						<div className="text-xs uppercase tracking-[0.2em] text-slate-500">Recent activity</div>
						<h2 className="mt-2 text-xl font-semibold text-white">Render queue</h2>
					</div>

					<div className="mt-5 space-y-3">
						{recentRenders.length ? recentRenders.map((job) => (
							<div key={job.id} className="rounded-xl border border-surface-700 bg-surface-800 px-4 py-3">
								<div className="flex items-start justify-between gap-3">
									<div className="min-w-0">
										<div className="truncate text-sm font-medium text-white">{job.message ?? `Render ${job.candidate_id ?? ''}`.trim()}</div>
										<div className="mt-1 text-xs text-slate-400">{job.video_id ?? 'Unknown project'} • {formatDate(job.updated_at)}</div>
									</div>
									<Badge variant={job.status === 'completed' ? 'completed' : job.status === 'failed' || job.status === 'interrupted' ? 'failed' : job.status === 'running' ? 'running' : 'queued'}>{job.status}</Badge>
								</div>
								<div className="mt-2 text-xs text-slate-500">{job.stage ?? 'Queued'}{job.percent != null ? ` • ${Math.max(0, Math.min(100, job.percent))}%` : ''}</div>
							</div>
						)) : <EmptyState title="No render activity yet" description="Rendered clips and retry history will appear here once jobs are submitted." />}
					</div>
				</Card>
			</section>

			<section className="grid gap-4 lg:grid-cols-3">
				<Card className="p-6 lg:col-span-2">
					<div className="flex items-center justify-between gap-4">
						<div>
							<div className="text-xs uppercase tracking-[0.2em] text-slate-500">What to do next</div>
							<h2 className="mt-2 text-xl font-semibold text-white">Keep the workspace moving</h2>
						</div>
						<Button type="button" variant="secondary" onClick={() => navigate('/projects')}>Open project browser</Button>
					</div>
					<div className="mt-5 grid gap-3 md:grid-cols-3">
						<div className="rounded-xl border border-surface-700 bg-surface-800 p-4 text-sm text-slate-300">Start a new analysis from a supported video URL.</div>
						<div className="rounded-xl border border-surface-700 bg-surface-800 p-4 text-sm text-slate-300">Review candidates, trims, and captions in the project workspace.</div>
						<div className="rounded-xl border border-surface-700 bg-surface-800 p-4 text-sm text-slate-300">Manage finished clips in the library and render queue.</div>
					</div>
				</Card>

				<Card className="overflow-hidden">
					{recentProjects[0]?.source_thumbnail_url ? (
						<img src={resolveMediaUrl(recentProjects[0].source_thumbnail_url) ?? recentProjects[0].source_thumbnail_url} alt={recentProjects[0].title ?? recentProjects[0].video_id} className="h-full w-full object-cover" />
					) : (
						<div className="flex min-h-[18rem] items-center justify-center p-6 text-center text-sm text-slate-500">Recent project preview appears here when a thumbnail is available.</div>
					)}
				</Card>
			</section>
		</div>
	);
}