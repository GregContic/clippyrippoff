import { afterEach, describe, expect, it, vi } from 'vitest';
import { uploadVideo } from './client';
import type { UploadConfig } from './types';

const uploadConfig: UploadConfig = {
  max_upload_bytes: 4,
  multipart_threshold_bytes: 2,
  part_size_bytes: 2,
  allowed_extensions: ['.mp4'],
  direct_upload: true,
};

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
}

afterEach(() => vi.unstubAllGlobals());

describe('uploadVideo validation', () => {
  it('rejects files exceeding the configured upload limit before creating an upload session', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(uploadConfig));
    vi.stubGlobal('fetch', fetchMock);

    await expect(uploadVideo(
      new File(['12345'], 'large.mp4', { type: 'video/mp4' }),
      new AbortController().signal,
      vi.fn(),
      vi.fn(),
    )).rejects.toThrow('File exceeds the maximum supported size of 1 MiB.');
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it('rejects unsupported file types before creating an upload session', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(uploadConfig));
    vi.stubGlobal('fetch', fetchMock);

    await expect(uploadVideo(
      new File(['text'], 'notes.txt', { type: 'text/plain' }),
      new AbortController().signal,
      vi.fn(),
      vi.fn(),
    )).rejects.toThrow('Unsupported video format. Accepted formats: .mp4.');
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});
