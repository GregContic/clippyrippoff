import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { UploadConfig } from '../api/types';
import { AnalyzePage } from './AnalyzePage';

const { navigate, api } = vi.hoisted(() => ({
  navigate: vi.fn(),
  api: {
    analyzeVideo: vi.fn(),
    cancelVideoUpload: vi.fn(),
    getUploadConfig: vi.fn(),
    listProjects: vi.fn(),
    uploadVideo: vi.fn(),
  },
}));

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return { ...actual, useNavigate: () => navigate };
});

vi.mock('../api/client', () => api);

const uploadConfig: UploadConfig = {
  max_upload_bytes: 1024,
  multipart_threshold_bytes: 512,
  part_size_bytes: 256,
  allowed_extensions: ['.mp4', '.mov'],
  direct_upload: true,
};

afterEach(cleanup);

function selectVideo(file: File) {
  fireEvent.change(screen.getByLabelText('Select a video file'), { target: { files: [file] } });
}

async function waitForUploadConfig() {
  await waitFor(() => expect((screen.getByLabelText('Select a video file') as HTMLInputElement).accept).toBe('.mp4,.mov'));
}

describe('AnalyzePage video uploads', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getUploadConfig.mockResolvedValue(uploadConfig);
    api.listProjects.mockResolvedValue({ items: [] });
  });

  it('shows upload initialization failures and restores the upload button', async () => {
    api.uploadVideo.mockRejectedValue(new Error('Upload initialization failed.'));
    render(<AnalyzePage />);
    const file = new File(['video'], 'clip.mp4', { type: 'video/mp4' });

    await waitForUploadConfig();
    selectVideo(file);

    expect(await screen.findByText('Upload initialization failed.')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Upload video' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it.each([
    ['invalid file types', 'Unsupported video format. Accepted formats: .mp4, .mov.', 'notes.txt'],
    ['oversized files', 'File exceeds the maximum supported size of 1 MiB.', 'large.mp4'],
  ])('displays validation errors for %s', async (_caseName, message, filename) => {
    api.uploadVideo.mockRejectedValue(new Error(message));
    render(<AnalyzePage />);

    await waitForUploadConfig();
    selectVideo(new File(['video'], filename, { type: 'video/mp4' }));

    expect(await screen.findByText(message)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Upload video' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('navigates to the project after upload completion starts analysis', async () => {
    api.uploadVideo.mockResolvedValue({ video_id: 'project-123' });
    render(<AnalyzePage />);

    await waitForUploadConfig();
    selectVideo(new File(['video'], 'clip.mp4', { type: 'video/mp4' }));

    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/projects/project-123'));
  });

  it('cancels an active upload and restores the button', async () => {
    api.uploadVideo.mockImplementation((_file: File, signal: AbortSignal) => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('Upload canceled.', 'AbortError')), { once: true });
    }));
    render(<AnalyzePage />);

    await waitForUploadConfig();
    selectVideo(new File(['video'], 'clip.mp4', { type: 'video/mp4' }));
    const cancelButton = await screen.findByRole('button', { name: 'Cancel upload' });
    fireEvent.click(cancelButton);

    await waitFor(() => expect((screen.getByRole('button', { name: 'Upload video' }) as HTMLButtonElement).disabled).toBe(false));
  });
});
