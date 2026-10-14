import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiRequestError, getProject } from './client';

afterEach(() => vi.unstubAllGlobals());

describe('API error responses', () => {
  it('replaces HTML 502 gateway bodies with a concise retryable message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      '<!doctype html><html><body><h1>Bad Gateway</h1><p>proxy detail</p></body></html>',
      { status: 502, headers: { 'Content-Type': 'text/html' } },
    )));

    const request = getProject('video-1');
    await expect(request).rejects.toMatchObject({
      name: 'ApiRequestError',
      status: 502,
      retryable: true,
      message: 'The server is temporarily unavailable (HTTP 502). Retrying automatically.',
    });
    await expect(request).rejects.not.toThrow('Bad Gateway');
    await expect(request).rejects.not.toThrow('<html>');
  });

  it('does not expose HTML error bodies when the gateway omits a content type', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      '<html><body>upstream error</body></html>',
      { status: 500 },
    )));

    await expect(getProject('video-1')).rejects.toMatchObject({
      name: 'ApiRequestError',
      message: 'The server is temporarily unavailable (HTTP 500). Retrying automatically.',
    });
  });

  it('does not expose HTML snippets mislabeled as plain text', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      '<h1>Request rejected</h1><p>internal gateway details</p>',
      { status: 404, headers: { 'Content-Type': 'text/plain' } },
    )));

    await expect(getProject('missing')).rejects.toMatchObject({
      name: 'ApiRequestError',
      message: 'The server returned an unreadable error (HTTP 404).',
    });
  });

  it('preserves structured API details for non-retryable JSON errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: 'Project not found.' }),
      { status: 404, headers: { 'Content-Type': 'application/json' } },
    )));

    await expect(getProject('missing')).rejects.toEqual(
      expect.objectContaining<ApiRequestError>({
        name: 'ApiRequestError',
        message: 'Project not found.',
        status: 404,
        retryable: false,
      }),
    );
  });
});
