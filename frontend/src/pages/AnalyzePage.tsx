import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { analyzeVideo, cancelVideoUpload, getUploadConfig, listProjects, uploadVideo, type UploadSessionState } from '../api/client';
import type { ProjectSummary, UploadConfig } from '../api/types';
import { formatBytes, formatDate, formatDuration } from '../lib/format';
import { Badge, Button, Card, EmptyState } from '../components/ui';
import { UrlInput } from '../components/UrlInput';

export function AnalyzePage() {
	const navigate = useNavigate();
	const [url, setUrl] = useState('');
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [projects, setProjects] = useState<ProjectSummary[]>([]);
	const [uploadConfig, setUploadConfig] = useState<UploadConfig | null>(null);
	const [uploadConfigError, setUploadConfigError] = useState<string | null>(null);
	const [uploadProgress, setUploadProgress] = useState({ bytes: 0, total: 0, speed: 0 });
	const [uploadFile, setUploadFile] = useState<File | null>(null);
	const [uploadSession, setUploadSession] = useState<UploadSessionState | undefined>();
	const [uploadError, setUploadError] = useState<string | null>(null);
	const [uploading, setUploading] = useState(false);
	const uploadController = useRef<AbortController | null>(null);
	const busy = useRef(false);

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
		getUploadConfig()
			.then((config) => {
				if (active) setUploadConfig(config);
			})
			.catch((cause: unknown) => {
				if (active) setUploadConfigError(cause instanceof Error ? cause.message : 'Unable to load upload settings.');
			});
		return () => {
			active = false;
		};
	}, []);

	const recentProjects = useMemo(() => [...projects].sort((left, right) => (right.latest_activity_at ?? right.updated_at ?? '').localeCompare(left.latest_activity_at ?? left.updated_at ?? '')).slice(0, 6), [projects]);
	const transferComplete = uploadProgress.total > 0 && uploadProgress.bytes >= uploadProgress.total;

	async function handleUpload(file: File, resumed?: UploadSessionState) {
		if (busy.current) {
			return;
		}
		busy.current = true;
		setLoading(true);
		setUploading(true);
		setError(null);
		setUploadError(null);
		setUploadFile(file);
		if (!resumed) {
			setUploadSession(undefined);
			setUploadProgress({ bytes: 0, total: file.size, speed: 0 });
		}
		const controller = new AbortController();
		uploadController.current = controller;
		let previousAt = performance.now();
		let previousBytes = 0;
		let currentSpeed = 0;
		try {
			const response = await uploadVideo(
				file,
				controller.signal,
				(bytes, total) => {
					const now = performance.now();
					const elapsed = (now - previousAt) / 1000;
					if (elapsed > 0.25) {
						currentSpeed = Math.max(0, (bytes - previousBytes) / elapsed);
					}
					if (elapsed > 0.25) {
						previousAt = now;
						previousBytes = bytes;
					}
					setUploadProgress({ bytes, total, speed: currentSpeed });
				},
				setUploadSession,
				resumed,
			);
			setUploadProgress((progress) => ({ ...progress, bytes: file.size, total: file.size }));
			navigate(`/projects/${response.video_id}`);
		} catch (cause) {
			if (cause instanceof DOMException && cause.name === 'AbortError') {
				setUploadSession(undefined);
				setUploadFile(null);
				setUploadProgress({ bytes: 0, total: 0, speed: 0 });
			} else {
				setUploadError(cause instanceof Error ? cause.message : 'Unable to upload the video.');
			}
		} finally {
			uploadController.current = null;
			setUploading(false);
			setLoading(false);
			busy.current = false;
		}
	}

	async function handleAnalyze() {
		if (busy.current) {
			return;
		}
		if (!url.trim()) {
			setError('Paste a supported video URL first.');
			return;
		}

		busy.current = true;
		setLoading(true);
		setError(null);
		try {
			const response = await analyzeVideo(url.trim());
			navigate(`/projects/${response.video_id}`);
		} catch (cause) {
			setError(cause instanceof Error ? cause.message : 'Unable to start analysis.');
		} finally {
			setLoading(false);
			busy.current = false;
		}
	}

	async function cancelUpload() {
		if (uploadController.current) {
			uploadController.current.abort();
			return;
		}
		if (uploadSession) {
			try {
				await cancelVideoUpload(uploadSession.upload.upload_id);
			} catch (cause) {
				setUploadError(cause instanceof Error ? cause.message : 'Unable to clean up the canceled upload.');
				return;
			}
		}
		setUploadSession(undefined);
		setUploadFile(null);
		setUploadProgress({ bytes: 0, total: 0, speed: 0 });
		setUploadError(null);
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
							<UrlInput
								value={url}
								onChange={setUrl}
								onSubmit={handleAnalyze}
								onUpload={handleUpload}
								loading={loading}
								busyLabel={uploading ? (transferComplete ? 'Starting analysis...' : 'Uploading...') : 'Analyzing...'}
								uploadDisabled={!uploadConfig || (import.meta.env.PROD && !uploadConfig.direct_upload)}
								uploadAccept={uploadConfig?.allowed_extensions.join(',')}
							/>
							{uploadConfig ? (
								<p className="text-xs text-slate-500">
									Maximum {formatBytes(uploadConfig.max_upload_bytes)} · {uploadConfig.allowed_extensions.join(', ')}
									{!uploadConfig.direct_upload ? ' · local-development upload mode' : ' · uploads go directly to private R2 storage'}
								</p>
							) : uploadConfigError ? (
								<p className="text-sm text-danger-100">{uploadConfigError}</p>
							) : (
								<p className="text-xs text-slate-500">Loading upload limits…</p>
							)}
							{import.meta.env.PROD && uploadConfig && !uploadConfig.direct_upload ? (
								<p className="text-sm text-danger-100">Video uploads are disabled in production until STORAGE_BACKEND=r2 is configured; this avoids routing large files through hosting request limits.</p>
							) : null}
							{uploading || uploadError ? (
								<div className="space-y-3 rounded-xl border border-surface-700 bg-surface-800 p-4">
									<div className="flex items-center justify-between gap-3 text-sm text-slate-300">
										<span>{uploading ? (transferComplete ? 'Verifying upload and starting processing…' : `Uploading ${uploadFile?.name ?? 'video'}…`) : uploadError ? 'Upload paused' : 'Upload'}</span>
										<span>{uploadProgress.total ? `${Math.floor((uploadProgress.bytes / uploadProgress.total) * 100)}%` : '0%'}</span>
									</div>
									<div className="h-2 overflow-hidden rounded-full bg-surface-700">
										<div className="h-full rounded-full bg-accent-400 transition-[width]" style={{ width: `${uploadProgress.total ? Math.min(100, (uploadProgress.bytes / uploadProgress.total) * 100) : 0}%` }} />
									</div>
									<div className="flex flex-wrap justify-between gap-2 text-xs text-slate-400">
										<span>{formatBytes(uploadProgress.bytes)} / {formatBytes(uploadProgress.total)}</span>
										<span>{uploadProgress.speed > 0 ? `${formatBytes(uploadProgress.speed)}/s` : 'Calculating speed…'}</span>
									</div>
									{uploadError ? <p className="text-sm text-danger-100">{uploadError}</p> : null}
									<div className="flex gap-2">
										{uploadError && uploadFile ? (
											<Button type="button" onClick={() => void handleUpload(uploadFile, uploadSession)}>Retry upload</Button>
										) : null}
										{(uploading && !transferComplete) || uploadError ? <Button type="button" variant="secondary" onClick={() => void cancelUpload()}>Cancel upload</Button> : null}
									</div>
								</div>
							) : null}
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