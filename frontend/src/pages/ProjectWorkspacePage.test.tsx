import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { BatchResponse, Candidate, CaptionPreset, ProjectSummary, ProjectMusicAsset } from '../api/types';
import { ProjectWorkspacePage } from './ProjectWorkspacePage';

const { api } = vi.hoisted(() => ({
  api: {
    analyzeVideo: vi.fn(),
    createBatch: vi.fn(),
    createCompilation: vi.fn(),
    deleteRender: vi.fn(),
    deleteLibraryFile: vi.fn(),
    getCandidates: vi.fn(),
    getCompilation: vi.fn(),
    getProject: vi.fn(),
    getProjectFiles: vi.fn(),
    getProjectMusic: vi.fn(),
    getProjectRenders: vi.fn(),
    getBatch: vi.fn(),
    listCaptionPresets: vi.fn(),
    renderCandidateOverride: vi.fn(),
    renderCandidates: vi.fn(),
    resolveMediaUrl: vi.fn((path: string) => path),
    uploadProjectMusic: vi.fn(),
  },
}));

vi.mock('../api/client', () => api);

vi.mock('../components/CandidateGrid', () => ({
  CandidateGrid: ({ onSelectAll, onRender }: { onSelectAll: () => void; onRender: () => void }) => (
    <div>
      <button type="button" onClick={onSelectAll}>Select test candidate</button>
      <button type="button" onClick={onRender}>Render selected test candidate</button>
    </div>
  ),
}));

vi.mock('../components/RenderQueue', () => ({
  RenderQueue: () => <div>Project render queue</div>,
}));

const project: ProjectSummary = {
  video_id: 'video-1',
  title: 'Test project',
  status: 'completed',
  candidate_count: 1,
  rendered_count: 0,
  rendered_urls: [],
};

const candidate: Candidate = {
  id: 2,
  start: 10,
  end: 28,
  duration: 18,
  candidate_score: 0.9,
  signals: {},
  audio_peak: 0,
  relative_audio_peak: 0,
  audio_level: 'normal',
  reaction_detected: false,
  matched_keywords: [],
  scene_change_score: 0,
  trigger_types: [],
};

const preset: CaptionPreset = {
  id: 'preset-bold',
  name: 'Bold captions',
  built_in: false,
  version: 1,
  settings: {},
};

const music: ProjectMusicAsset = {
  asset_id: 'music-1',
  project_id: 'video-1',
  filename: 'theme.mp3',
  content_type: 'audio/mpeg',
  size_bytes: 100,
  duration_seconds: 12,
};

function makeBatch(status = 'queued'): BatchResponse {
  return {
    batch_id: 'batch-1',
    project_id: 'video-1',
    parent_job_id: 'parent-1',
    status,
    percent: status === 'running' ? 45 : 0,
    child_job_ids: [],
    children: [],
    target_duration_seconds: 30,
    minimum_spacing_seconds: 5,
    created_at: '2026-10-14T00:00:00Z',
  };
}

function renderWorkspace() {
  return render(
    <MemoryRouter initialEntries={['/projects/video-1']}>
      <Routes>
        <Route path="/projects/:videoId" element={<ProjectWorkspacePage />} />
      </Routes>
    </MemoryRouter>,
  );
}

async function openTools() {
  await screen.findByRole('heading', { name: 'Test project' });
  fireEvent.click(screen.getByRole('button', { name: 'Create & Edit' }));
  await screen.findByRole('heading', { name: 'Batch Clips' });
}

afterEach(cleanup);

describe('ProjectWorkspacePage tools', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getProject.mockResolvedValue(project);
    api.getCandidates.mockResolvedValue({ candidates: [candidate], source_duration: 60 });
    api.getProjectRenders.mockResolvedValue([]);
    api.getProjectFiles.mockResolvedValue({ items: [] });
    api.getProjectMusic.mockResolvedValue([music]);
    api.listCaptionPresets.mockResolvedValue([preset]);
    api.getBatch.mockResolvedValue(makeBatch('running'));
    api.getCompilation.mockResolvedValue(null);
    api.createBatch.mockResolvedValue(makeBatch());
    api.createCompilation.mockResolvedValue({
      compilation_id: 'comp-1',
      project_id: 'video-1',
      parent_job_id: 'comp-job-1',
      status: 'queued',
      progress: 0,
      segments: [],
      effective_duration_seconds: 0,
      created_at: '2026-10-14T00:00:00Z',
    });
    api.renderCandidates.mockResolvedValue({ video_id: 'video-1', render_job_ids: ['render-1'] });
  });

  it('provides a dedicated tools tab with keyboard-focusable links to each feature', async () => {
    renderWorkspace();
    await openTools();

    for (const label of ['Batch Clips', 'Auto-Compilation', 'Smart Editing']) {
      expect(screen.getByRole('link', { name: label })).toBeTruthy();
      expect(screen.getByRole('heading', { name: label })).toBeTruthy();
    }

    const batchLink = screen.getByRole('link', { name: 'Batch Clips' });
    batchLink.focus();
    expect(document.activeElement).toBe(batchLink);
    expect(batchLink.getAttribute('href')).toBe('#batch-clips');
  });

  it('explains unavailable analysis prerequisites and disables batch and compilation actions', async () => {
    api.getProject.mockResolvedValue({ ...project, status: 'running', candidate_count: 0 });
    api.getCandidates.mockClear();
    renderWorkspace();
    await openTools();

    expect(screen.getByText(/unavailable until analysis completes/)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Generate batch' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Create compilation' }) as HTMLButtonElement).disabled).toBe(true);
    expect(api.getCandidates).not.toHaveBeenCalled();
  });

  it('explains completed analysis with no candidates', async () => {
    api.getProject.mockResolvedValue({ ...project, candidate_count: 0 });
    api.getCandidates.mockClear();
    renderWorkspace();
    await openTools();

    expect(screen.getByText(/completed without candidates/)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Generate batch' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('keeps project music listing and upload available in Smart Editing', async () => {
    const uploadedMusic = { ...music, asset_id: 'music-2', filename: 'uploaded.mp3' };
    api.uploadProjectMusic.mockResolvedValue(uploadedMusic);
    const { container } = renderWorkspace();
    await openTools();
    await screen.findByRole('option', { name: 'theme.mp3 · 0:12' });
    const file = new File(['audio'], 'uploaded.mp3', { type: 'audio/mpeg' });
    const input = container.querySelector<HTMLInputElement>('input[type="file"][accept*="audio"]');

    expect(input).not.toBeNull();
    fireEvent.change(input as HTMLInputElement, { target: { files: [file] } });

    expect(await screen.findByRole('option', { name: 'uploaded.mp3 · 0:12' })).toBeTruthy();
    expect(api.getProjectMusic).toHaveBeenCalledWith('video-1');
    expect(api.uploadProjectMusic).toHaveBeenCalledWith('video-1', file);
  });

  it('keeps batch status and clip details visible on Renders after submission', async () => {
    api.getBatch.mockResolvedValue({
      ...makeBatch('partially_completed'),
      percent: 70,
      children: [
        { job_id: 'child-1', status: 'completed', percent: 100, candidate_id: 2, output_url: '/media/clip.mp4' },
        { job_id: 'child-2', status: 'failed', percent: 35, candidate_id: 3, error: 'Render failed.' },
      ],
    });
    renderWorkspace();
    await openTools();
    fireEvent.click(screen.getByRole('button', { name: 'Generate batch' }));

    expect(await screen.findByText(/Partially completed · 70% · 1\/2 clips completed · 1 failed/)).toBeTruthy();
    expect(api.createBatch).toHaveBeenCalledOnce();
    expect(screen.getByText('Project render queue')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Open clip' }).getAttribute('href')).toBe('/media/clip.mp4');
    expect(screen.getByText('Render failed.')).toBeTruthy();
  });

  it('recovers from polling failures with the manual refresh control', async () => {
    api.getBatch
      .mockRejectedValueOnce(new Error('Temporary network failure.'))
      .mockResolvedValueOnce(makeBatch('completed'));
    renderWorkspace();
    await openTools();
    fireEvent.click(screen.getByRole('button', { name: 'Generate batch' }));

    expect(await screen.findByText(/Could not refresh batch status: Temporary network failure/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Refresh status' }));
    expect(await screen.findByText(/Completed · 0% · 0\/0 clips completed/)).toBeTruthy();
    expect(screen.queryByText(/Could not refresh batch status/)).toBeNull();
  });

  it('cleans up the single batch polling interval when the workspace unmounts', async () => {
    const setInterval = vi.spyOn(window, 'setInterval');
    const clearInterval = vi.spyOn(window, 'clearInterval');
    const view = renderWorkspace();
    await openTools();
    fireEvent.click(screen.getByRole('button', { name: 'Generate batch' }));
    await waitFor(() => expect(api.getBatch).toHaveBeenCalled());
    const intervalId = setInterval.mock.results.find((result) => result.type === 'return')?.value;

    view.unmount();

    expect(setInterval).toHaveBeenCalledWith(expect.any(Function), 2000);
    expect(clearInterval).toHaveBeenCalledWith(intervalId);
    setInterval.mockRestore();
    clearInterval.mockRestore();
  });

  it('continues passing smart-edit settings to individual renders, batches, and compilations', async () => {
    renderWorkspace();
    await openTools();

    fireEvent.click(screen.getByLabelText('Opening hook overlay'));
    fireEvent.change(screen.getByPlaceholderText('Add a short opening hook'), { target: { value: 'Play of the game' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add interval' }));
    fireEvent.change(screen.getByLabelText('Caption preset'), { target: { value: 'preset-bold' } });
    await screen.findByRole('option', { name: 'theme.mp3 · 0:12' });
    fireEvent.change(screen.getByDisplayValue('Music disabled'), { target: { value: 'music-1' } });
    fireEvent.change(screen.getByLabelText(/Music volume/), { target: { value: '0.35' } });
    fireEvent.change(screen.getByLabelText('Fade in (seconds)'), { target: { value: '1.5' } });
    fireEvent.click(screen.getByLabelText('Duck music under original audio'));

    fireEvent.click(screen.getByRole('button', { name: 'Candidates' }));
    fireEvent.click(screen.getByRole('button', { name: 'Select test candidate' }));
    fireEvent.click(screen.getByRole('button', { name: 'Render selected test candidate' }));
    await waitFor(() => expect(api.renderCandidates).toHaveBeenCalled());

    fireEvent.click(screen.getByRole('button', { name: 'Create & Edit' }));
    fireEvent.click(screen.getByRole('button', { name: /Generate batch/ }));
    await waitFor(() => expect(api.createBatch).toHaveBeenCalled());

    const expectedEditing = {
      schema_version: 1,
      zoom_intervals: [{ start_seconds: 1, end_seconds: 3, scale: 1.15 }],
      transition: 'hard_cut',
      transition_duration_seconds: 0.5,
      hook: expect.objectContaining({ text: 'Play of the game', position: 'center' }),
      music: expect.objectContaining({
        asset_id: 'music-1',
        volume: 0.35,
        loop: true,
        fade_in_seconds: 1.5,
        duck_original_audio: true,
      }),
      caption_preset_id: 'preset-bold',
    };
    expect(api.renderCandidates.mock.calls[0][2]).toEqual(expectedEditing);
    expect(api.createBatch.mock.calls[0][1].editing).toEqual(expectedEditing);

    fireEvent.click(screen.getByRole('button', { name: 'Candidates' }));
    fireEvent.click(screen.getByRole('button', { name: 'Create & Edit' }));
    fireEvent.click(screen.getByLabelText('Crossfade between compilation segments'));
    fireEvent.click(screen.getByRole('button', { name: 'Candidates' }));
    fireEvent.click(screen.getByRole('button', { name: 'Create & Edit' }));
    fireEvent.click(screen.getByRole('button', { name: 'Create compilation' }));

    await waitFor(() => expect(api.createCompilation).toHaveBeenCalled());
    expect(api.createCompilation.mock.calls[0][1].editing).toEqual({
      ...expectedEditing,
      transition: 'crossfade',
      transition_duration_seconds: 0.5,
    });
  });
});
